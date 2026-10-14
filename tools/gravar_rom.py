"""Planeja (e, com --executar, grava) a ROM de estoque inteira pelo mtkclient.

Uso:
  python gravar_rom.py <pasta_da_rom> <logs\\particoes.txt>                -> so mostra o plano
  python gravar_rom.py <pasta_da_rom> <logs\\particoes.txt> --executar <python> <mtk.py>

Nunca grava as particoes com IMEI/calibracao, o preloader nem os dados do usuario.
Cada imagem de slot (boot, lk, vbmeta...) e gravada em _a E _b, para nao depender
de qual slot o aparelho escolher.
"""
import os
import re
import struct
import subprocess
import sys
import zlib

NAO_GRAVAR = {
    # IMEI, calibracao e seguranca: ficam como estao
    "nvram", "nvdata", "nvcfg", "proinfo", "protect1", "protect2", "persist",
    "seccfg", "otp", "flashinfo", "frp", "sec1", "md_udc",
    # preloader: o atual funciona e o BROM continua acessivel sem ele
    "preloader",
    # dados e estado do usuario/bootloader
    "userdata", "metadata", "expdb", "boot_para", "para", "misc", "tranfs",
}
SPARSE_MAGIC = 0xED26FF3A
LP_GEOMETRY_MAGIC = 0x616C4467
LP_HEADER_MAGIC = 0x414C5030


def ler_texto(caminho):
    dados = open(caminho, "rb").read()
    if dados[:2] in (b"\xff\xfe", b"\xfe\xff"):
        txt = dados.decode("utf-16")
    else:
        txt = dados.decode("utf-8", "replace")
    return re.sub(r"\x1b\[[0-9;]*m", "", txt)


def ler_gpt(caminho):
    gpt = {}
    for m in re.finditer(r"^(\w+):\s+Offset 0x([0-9a-f]+), Length 0x([0-9a-f]+)",
                         ler_texto(caminho), re.M | re.I):
        gpt[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    return gpt


def achar_scatter(pasta):
    for raiz, _, arquivos in os.walk(pasta):
        for nome in arquivos:
            low = nome.lower()
            if "scatter" in low and low.endswith((".txt", ".xml")):
                return os.path.join(raiz, nome)
    return None


def ler_scatter(caminho):
    """Retorna [(particao, arquivo, tamanho_no_scatter)] so das que tem arquivo para gravar."""
    txt = ler_texto(caminho)
    blocos = re.split(r"partition_index", txt)[1:]
    itens = []
    for b in blocos:
        def campo(nome):
            m = re.search(rf"{nome}\s*[:>]\s*([^\s<]+)", b)
            return m.group(1) if m else ""
        nome, arq = campo("partition_name"), campo("file_name")
        if not nome or not arq or arq.upper() == "NONE":
            continue
        if campo("is_download").lower() == "false":
            continue
        tam = campo("partition_size")
        itens.append((nome, arq, int(tam, 16) if tam.startswith("0x") else 0))
    return itens


def tamanho_real(caminho):
    """Tamanho depois de 'desempacotar' (imagens sparse ocupam mais quando gravadas)."""
    with open(caminho, "rb") as f:
        cab = f.read(28)
    if len(cab) == 28 and struct.unpack_from("<I", cab)[0] == SPARSE_MAGIC:
        blk_sz, total_blks = struct.unpack_from("<II", cab, 12)
        return blk_sz * total_blks, True
    return os.path.getsize(caminho), False


def desempacotar_sparse(origem, destino):
    with open(origem, "rb") as f, open(destino, "wb") as out:
        cab = f.read(28)
        _, _, _, file_hdr, chunk_hdr, blk_sz, total_blks, total_chunks, _ = struct.unpack("<IHHHHIIII", cab)
        f.seek(file_hdr)
        for _ in range(total_chunks):
            tipo, _, blocos, total = struct.unpack("<HHII", f.read(12))
            f.seek(chunk_hdr - 12, 1)
            n = blocos * blk_sz
            if tipo == 0xCAC1:  # raw
                restante = n
                while restante:
                    pedaco = f.read(min(restante, 8 << 20))
                    out.write(pedaco)
                    restante -= len(pedaco)
            elif tipo == 0xCAC2:  # fill
                padrao = f.read(4) * (1 << 18)
                restante = n
                while restante:
                    out.write(padrao[:min(restante, len(padrao))])
                    restante -= min(restante, len(padrao))
            elif tipo == 0xCAC3:  # dont care
                out.seek(n, 1)
            else:  # crc
                f.seek(total - chunk_hdr, 1)
        out.truncate(blk_sz * total_blks)


def ler_inicio_logico(caminho, tamanho):
    """Le os primeiros bytes da imagem como ela fica gravada (funciona com sparse)."""
    with open(caminho, "rb") as f:
        cab = f.read(28)
        if struct.unpack_from("<I", cab)[0] != SPARSE_MAGIC:
            f.seek(0)
            return f.read(tamanho)
        _, _, _, file_hdr, chunk_hdr, blk_sz, _, total_chunks, _ = struct.unpack("<IHHHHIIII", cab)
        f.seek(file_hdr)
        dados = bytearray()
        for _ in range(total_chunks):
            if len(dados) >= tamanho:
                break
            tipo, _, blocos, total = struct.unpack("<HHII", f.read(12))
            f.seek(chunk_hdr - 12, 1)
            n = blocos * blk_sz
            if tipo == 0xCAC1:
                parte = min(n, tamanho - len(dados))
                dados += f.read(parte)
                f.seek(n - parte, 1)
            elif tipo == 0xCAC2:
                dados += f.read(4) * (n // 4)
            elif tipo == 0xCAC3:
                dados += bytes(n)
            else:
                f.seek(total - chunk_hdr, 1)
        return bytes(dados[:tamanho])


def particoes_do_super(caminho):
    """Lista as particoes logicas (system_a, vendor_b...) dentro do super.img."""
    img = ler_inicio_logico(caminho, 1 << 20)
    if len(img) < 12288 + 256 or struct.unpack_from("<I", img, 4096)[0] != LP_GEOMETRY_MAGIC:
        return None
    meta = 4096 * 3
    if struct.unpack_from("<I", img, meta)[0] != LP_HEADER_MAGIC:
        return None
    header_size = struct.unpack_from("<I", img, meta + 8)[0]
    p_off, p_num, p_sz = struct.unpack_from("<III", img, meta + 80)
    e_off, e_num, e_sz = struct.unpack_from("<III", img, meta + 92)
    tabelas = meta + header_size
    extents = [struct.unpack_from("<Q", img, tabelas + e_off + i * e_sz)[0] for i in range(e_num)]
    nomes = []
    for i in range(p_num):
        base = tabelas + p_off + i * p_sz
        nome = img[base:base + 36].split(b"\0")[0].decode()
        primeiro, qtd = struct.unpack_from("<II", img, base + 40)
        setores = sum(extents[primeiro:primeiro + qtd])
        nomes.append((nome, setores * 512))
    return nomes


def ler_controle_ab(caminho):
    """Le o controle A/B do Android (struct bootloader_control, magic 'BCAB') no misc.

    Retorna (offset, dados_do_misc, prioridades {a: p, b: p}) ou None se nao achar/CRC errado.
    """
    if not os.path.exists(caminho):
        return None
    dados = bytearray(open(caminho, "rb").read())
    pos = dados.find(b"BCAB") - 4
    if pos < 0:
        return None
    ctrl = dados[pos:pos + 32]
    if struct.unpack_from("<I", ctrl, 28)[0] != zlib.crc32(bytes(ctrl[:28])):
        return None
    prioridades = {"a": ctrl[12] & 0xF, "b": ctrl[14] & 0xF}
    return pos, dados, prioridades


def misc_com_slot_a(pos, dados):
    """Copia do misc com o slot A na frente (prioridade 15) e o B logo atras (14)."""
    novo = bytearray(dados)
    novo[pos + 12] = (novo[pos + 12] & 0xF0) | 15
    novo[pos + 14] = (novo[pos + 14] & 0xF0) | 14
    struct.pack_into("<I", novo, pos + 28, zlib.crc32(bytes(novo[pos:pos + 28])))
    return bytes(novo)


def montar_plano(rom, gpt_txt):
    scatter = achar_scatter(rom)
    if not scatter:
        print(f"[ERRO] Nenhum arquivo *scatter*.txt/.xml dentro de {rom}")
        return None
    print(f"Scatter: {scatter}")
    pasta_imgs = os.path.dirname(scatter)
    gpt = ler_gpt(gpt_txt)
    if not gpt:
        print(f"[ERRO] Nao consegui ler a tabela de particoes de {gpt_txt} (rode a opcao 1).")
        return None

    plano, erros = [], []
    for nome, arq, tam_scatter in ler_scatter(scatter):
        base = re.sub(r"_[ab]$", "", nome)
        if nome in NAO_GRAVAR or base in NAO_GRAVAR:
            print(f"  pula     {nome:<18} {arq}")
            continue
        caminho = os.path.join(pasta_imgs, arq)
        if not os.path.exists(caminho):
            erros.append(f"{nome}: arquivo {arq} nao existe na pasta da ROM")
            continue
        alvos = [n for n in (base + "_a", base + "_b") if n in gpt] if base != nome else [nome]
        if not alvos or any(a not in gpt for a in alvos):
            erros.append(f"{nome}: o aparelho nao tem essa particao (layout diferente)")
            continue
        tam, sparse = tamanho_real(caminho)
        for alvo in alvos:
            tam_gpt = gpt[alvo][1]
            if tam > tam_gpt:
                erros.append(f"{alvo}: imagem {tam} bytes > particao {tam_gpt} bytes")
            if tam_scatter and tam_scatter != tam_gpt:
                erros.append(f"{alvo}: tamanho no scatter 0x{tam_scatter:x} != aparelho 0x{tam_gpt:x}")
        plano.append((alvos, caminho, sparse))
        print(f"  grava    {'+'.join(alvos):<18} {arq}  ({tam / 1048576:.1f} MB{', sparse' if sparse else ''})")

    super_img = next((c for a, c, _ in plano if a == ["super"]), None)
    logicas, so_slot_a = None, False
    if super_img:
        logicas = particoes_do_super(super_img)
        if logicas is None:
            print("\n  [AVISO] Nao consegui ler as particoes de dentro do super.img")
        else:
            print("\n  Dentro do super.img:")
            for n, t in logicas:
                print(f"     {n:<22} {t / 1048576:8.1f} MB")
            so_slot_a = not any(n.endswith("_b") and t for n, t in logicas)
            if so_slot_a:
                print("  [ATENCAO] O sistema so esta no slot A. O aparelho precisa ligar pelo slot A.")

    print("\n  Slot ativo hoje (do backup\\misc.bin):")
    ctrl = ler_controle_ab(os.path.join("backup", "misc.bin"))
    ativo = None
    if ctrl is None:
        print("     nao encontrado ou CRC invalido (rode a opcao 6 para reler o misc)")
    else:
        pos, dados, prio = ctrl
        ativo = max(prio, key=prio.get)
        print(f"     prioridade A={prio['a']}  B={prio['b']}  ->  slot ativo: {ativo.upper()}")
    if super_img and logicas and so_slot_a and ativo != "a":
        if ativo == "b" and "misc" in gpt:
            novo = os.path.join("backup", "misc_slot_a.bin")
            with open(novo, "wb") as f:
                f.write(misc_com_slot_a(pos, dados))
            plano.append((["misc"], novo, False))
            print(f"  grava    misc               {novo}  (so troca o slot ativo para A)")
        else:
            erros.append("a ROM so tem sistema no slot A e nao consegui confirmar/trocar o slot ativo. "
                         "Mande este plano para o Claude.")

    if erros:
        print("\n[PROBLEMAS] - NAO grave antes de resolver:")
        for e in erros:
            print(f"  - {e}")
        return None
    return plano, gpt


PEDACO = 256 << 20  # o super e gravado em pedacos de 256 MB para poder continuar de onde parou


def dividir_em_pedacos(raw, pasta, apagar_original):
    """Divide a imagem em arquivos de 256 MB (do fim para o comeco, encolhendo o original
    quando ele e nosso, para nao precisar de espaco em dobro no disco)."""
    marcador = os.path.join(pasta, "completo.txt")
    if os.path.exists(marcador):
        return int(open(marcador).read())
    os.makedirs(pasta, exist_ok=True)
    total = os.path.getsize(raw)
    qtd = (total + PEDACO - 1) // PEDACO
    print(f"Dividindo {os.path.basename(raw)} em {qtd} pedacos de 256 MB...")
    with open(raw, "r+b" if apagar_original else "rb") as f:
        for n in reversed(range(qtd)):
            destino = os.path.join(pasta, f"{n:03d}.bin")
            f.seek(n * PEDACO)
            with open(destino + ".tmp", "wb") as out:
                restante = min(PEDACO, total - n * PEDACO)
                while restante:
                    bloco = f.read(min(restante, 8 << 20))
                    out.write(bloco)
                    restante -= len(bloco)
            os.replace(destino + ".tmp", destino)
            if apagar_original:
                f.truncate(n * PEDACO)
    if apagar_original:
        os.remove(raw)
    with open(marcador, "w") as f:
        f.write(str(qtd))
    return qtd


def rodar_mtk(cmd, grupo, chaves_por_marca, feito_txt):
    """Roda o mtkclient mostrando a saida e salva cada gravacao confirmada na hora."""
    print("\n" + "=" * 62)
    print(f" Gravando {len(grupo)} item(ns): " + ", ".join(sorted({k.split('#')[0] for k in grupo})))
    print(" Conecte o cabo segurando VOLUME + e VOLUME - .")
    print("=" * 62)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace")
    ok = set()
    with open(feito_txt, "a") as feito:
        for linha in proc.stdout:
            if linha.startswith("Progress"):
                print(linha.rstrip("\n"), end="\r")
                continue
            print(linha, end="")
            # "Wrote <arq> to sector N ..." (w)  ou  "Wrote <arq> to offset 0x... ..." (wo)
            m = re.search(r"Wrote .+ to (sector \d+|offset 0x[0-9a-fA-F]+)", linha)
            if m and m.group(1).lower() in chaves_por_marca:
                chave = chaves_por_marca[m.group(1).lower()]
                ok.add(chave)
                feito.write(chave + "\n")
                feito.flush()
    proc.wait()
    return ok


def executar(plano, gpt, py, mtk):
    pasta_raw = os.path.join("firmware", "raw")
    os.makedirs(pasta_raw, exist_ok=True)
    feito_txt = os.path.join("logs", "rom_gravadas.txt")
    feitas = set(open(feito_txt).read().split()) if os.path.exists(feito_txt) else set()

    pequenas, pedacos = [], []
    for alvos, caminho, sparse in plano:
        grande = tamanho_real(caminho)[0] > 2 * PEDACO
        if grande and all(a in feitas for a in alvos):
            continue  # ja gravada inteira numa versao anterior desta ferramenta
        raw = caminho
        nome = os.path.basename(caminho)
        pasta_ped = os.path.join(pasta_raw, nome + ".partes")
        precisa_raw = sparse and not (grande and os.path.exists(os.path.join(pasta_ped, "completo.txt")))
        if precisa_raw:
            raw = os.path.join(pasta_raw, nome + ".raw")
            if not os.path.exists(raw):
                print(f"Desempacotando {nome} (pode demorar)...")
                desempacotar_sparse(caminho, raw + ".tmp")
                os.replace(raw + ".tmp", raw)
        if not grande:
            pequenas.extend((a, raw) for a in alvos)
            continue
        qtd = dividir_em_pedacos(raw, pasta_ped, apagar_original=sparse)
        for a in alvos:
            for n in range(qtd):
                arq = os.path.join(pasta_ped, f"{n:03d}.bin")
                pedacos.append((f"{a}#{n:03d}", gpt[a][0] + n * PEDACO, os.path.getsize(arq), arq))

    if feitas:
        print(f"Continuando de onde parou ({feito_txt}): {len(feitas)} item(ns) ja gravados.")

    grupo = [(a, c) for a, c in pequenas if a not in feitas]
    if grupo:
        cmd = [py, mtk, "w", ",".join(a for a, _ in grupo), ",".join(c for _, c in grupo)]
        marcas = {f"sector {gpt[a][0] // 512}": a for a, _ in grupo}
        ok = rodar_mtk(cmd, [a for a, _ in grupo], marcas, feito_txt)
        faltam = [a for a, _ in grupo if a not in ok]
        if faltam:
            print(f"\n[FALHOU] Nao confirmadas: {', '.join(faltam)}")
            print("Rode a opcao 9 de novo: ela continua so com o que faltou.")
            return 1

    grupo = [p for p in pedacos if p[0] not in feitas]
    if grupo:
        print(f"\nFaltam {len(grupo)} de {len(pedacos)} pedacos de 256 MB.")
        script = os.path.join("logs", "rom_script.txt")
        with open(script, "w") as f:
            for _, ini, tam, arq in grupo:
                f.write(f"wo {hex(ini)} {hex(tam)} {arq}\n")
        marcas = {f"offset {hex(ini)}": chave for chave, ini, _, _ in grupo}
        ok = rodar_mtk([py, mtk, "script", script], [c for c, _, _, _ in grupo], marcas, feito_txt)
        faltam = [c for c, _, _, _ in grupo if c not in ok]
        if faltam:
            print(f"\n[FALHOU] Gravados {len(grupo) - len(faltam)} de {len(grupo)} pedacos nesta rodada.")
            print("Rode a opcao 9 de novo: ela continua do proximo pedaco.")
            return 1

    print("\n[OK] Todas as particoes gravadas.")
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    resultado = montar_plano(sys.argv[1], sys.argv[2])
    if resultado is None:
        return 1
    plano, gpt = resultado
    if "--executar" not in sys.argv:
        print("\n[OK] Plano montado. Nada foi gravado.")
        return 0
    i = sys.argv.index("--executar")
    return executar(plano, gpt, sys.argv[i + 1], sys.argv[i + 2])


if __name__ == "__main__":
    sys.exit(main())
