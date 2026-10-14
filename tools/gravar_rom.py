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


def slot_no_misc(pasta_backup):
    """Procura a estrutura de controle A/B (magic 'BCAB') nos backups de misc/para."""
    achados = []
    for nome in ("misc.bin", "para.bin"):
        caminho = os.path.join(pasta_backup, nome)
        if not os.path.exists(caminho):
            continue
        dados = open(caminho, "rb").read()
        pos = dados.find(b"BCAB")
        if pos >= 4:
            sufixo = dados[pos - 4:pos].split(b"\0")[0].decode("ascii", "replace")
            achados.append(f"{nome}: controle A/B no offset 0x{pos - 4:x}, slot gravado '{sufixo}'"
                           f"  [{dados[pos - 4:pos + 28].hex(' ')}]")
        else:
            achados.append(f"{nome}: sem estrutura de controle A/B")
    return achados


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

    print("\n  Slot ativo hoje (do backup):")
    slots = slot_no_misc("backup")
    for linha in slots or ["(sem backup\\misc.bin - rode a opcao 6 antes)"]:
        print(f"     {linha}")
    if super_img and logicas and so_slot_a and not any("'_a'" in l for l in slots):
        erros.append("a ROM so tem sistema no slot A, mas o aparelho nao esta (ou nao se sabe se esta) "
                     "no slot A. Mande este plano para o Claude ajustar o slot antes de gravar.")

    if erros:
        print("\n[PROBLEMAS] - NAO grave antes de resolver:")
        for e in erros:
            print(f"  - {e}")
        return None
    return plano, gpt


def executar(plano, gpt, py, mtk):
    os.makedirs(os.path.join("firmware", "raw"), exist_ok=True)
    pequenas, grandes = [], []
    for alvos, caminho, sparse in plano:
        if sparse:
            raw = os.path.join("firmware", "raw", os.path.basename(caminho) + ".raw")
            if not os.path.exists(raw):
                print(f"Desempacotando {os.path.basename(caminho)} (pode demorar)...")
                desempacotar_sparse(caminho, raw)
            caminho = raw
        destino = grandes if os.path.getsize(caminho) > (512 << 20) else pequenas
        destino.extend((a, caminho) for a in alvos)

    feito_txt = os.path.join("logs", "rom_gravadas.txt")
    feitas = set(open(feito_txt).read().split()) if os.path.exists(feito_txt) else set()
    if feitas:
        print(f"Continuando: ja gravadas antes ({feito_txt}): {', '.join(sorted(feitas))}")
    for grupo in (pequenas, grandes):
        grupo = [(a, c) for a, c in grupo if a not in feitas]
        if not grupo:
            continue
        print("\n" + "=" * 62)
        print(" Gravando: " + ", ".join(a for a, _ in grupo))
        print(" Conecte o cabo segurando VOLUME + e VOLUME - .")
        print("=" * 62)
        cmd = [py, mtk, "w", ",".join(a for a, _ in grupo), ",".join(c for _, c in grupo)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace")
        saida = []
        for linha in proc.stdout:
            print(linha, end="")
            saida.append(linha)
        proc.wait()
        texto = "".join(saida)
        # o mtkclient escreve "Wrote <arquivo> to sector N" para cada particao gravada
        setores = {int(n) for n in re.findall(r"Wrote .+ to sector (\d+)", texto)}
        ok = [a for a, _ in grupo if gpt[a][0] // 512 in setores]
        with open(feito_txt, "a") as f:
            for a in ok:
                f.write(a + "\n")
        if len(ok) != len(grupo):
            faltam = [a for a, _ in grupo if a not in ok]
            print(f"\n[FALHOU] Nao confirmadas: {', '.join(faltam)}")
            print("Rode a opcao 9 de novo: ela continua so com o que faltou.")
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
