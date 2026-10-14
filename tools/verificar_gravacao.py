"""Diagnostico depois da gravacao da ROM (so leitura).

  python verificar_gravacao.py preparar <pasta_da_rom> <logs\\particoes.txt>
      -> escreve logs\\verif_script.txt (comandos de leitura para o mtkclient)
  python verificar_gravacao.py analisar <pasta_da_rom> <logs\\particoes.txt>
      -> compara o que foi lido com a ROM e extrai o texto da RAM para logs\\ram_texto.txt
"""
import os
import re
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gravar_rom  # noqa: E402

# regiao da RAM com o pstore/ramoops do kernel (ramoops.mem_address=0x4d010000) e vizinhanca
RAM_INICIO, RAM_TAMANHO = 0x4D000000, 0x1000000
LEITURA = 0x100000  # quanto ler do comeco de cada particao
CONFERIR = ["lk_a", "lk_b", "boot_a", "boot_b", "tee_a", "vbmeta_a", "super"]
PISTAS = re.compile(r"Linux version|Kernel panic|Kernel command line|slot_suffix|Unable to|BUG|"
                    r"Internal error|panic|verified|orange|LK_VER_TAG|\[LK|\[PROFILE\]|watchdog|wdt|"
                    r"Oops|init:|first stage|dm-verity|mount|fail", re.I)


def arquivos_da_rom(rom):
    scatter = gravar_rom.achar_scatter(rom)
    pasta = os.path.dirname(scatter)
    mapa = {}
    for nome, arq, _ in gravar_rom.ler_scatter(scatter):
        base = re.sub(r"_[ab]$", "", nome)
        for alvo in {nome, base + "_a", base + "_b"} if base != nome else {nome}:
            mapa[alvo] = os.path.join(pasta, arq)
    return mapa


def preparar(rom, gpt_txt):
    gpt = gravar_rom.ler_gpt(gpt_txt)
    linhas = [f"da peek {hex(RAM_INICIO)} {hex(RAM_TAMANHO)} --filename logs\\ram.bin"]
    for p in CONFERIR + ["misc"]:
        if p in gpt:
            ini, tam = gpt[p]
            linhas.append(f"ro {hex(ini)} {hex(min(tam, LEITURA))} logs\\verif_{p}.bin")
    with open(os.path.join("logs", "verif_script.txt"), "w") as f:
        f.write("\n".join(linhas) + "\n")
    print("Script de leitura: logs\\verif_script.txt")
    return 0


def analisar(rom, _gpt_txt):
    mapa = arquivos_da_rom(rom)
    print("== Conferencia da gravacao (primeiro 1 MB de cada particao)")
    for p in CONFERIR:
        lido = os.path.join("logs", f"verif_{p}.bin")
        if not os.path.exists(lido) or p not in mapa:
            print(f"   {p:<10} nao lido")
            continue
        dados = open(lido, "rb").read()
        esperado = gravar_rom.ler_inicio_logico(mapa[p], len(dados))
        esperado = esperado.ljust(len(dados), b"\0")
        print(f"   {p:<10} {'IGUAL a ROM' if dados == esperado else 'DIFERENTE da ROM !!!'}")

    misc = os.path.join("logs", "verif_misc.bin")
    if os.path.exists(misc):
        d = open(misc, "rb").read()
        pos = d.find(b"BCAB") - 4
        if pos >= 0:
            ctrl = d[pos:pos + 32]
            crc_ok = struct.unpack_from("<I", ctrl, 28)[0] == zlib.crc32(ctrl[:28])
            a, b = ctrl[12], ctrl[14]
            print(f"   misc       slot A: prioridade {a & 15}, tentativas {(a >> 4) & 7}, sucesso {a >> 7} | "
                  f"slot B: prioridade {b & 15}, tentativas {(b >> 4) & 7}, sucesso {b >> 7} | "
                  f"CRC {'ok' if crc_ok else 'ERRADO'}")
            print(f"              bytes: {ctrl.hex(' ')}")

    ram = os.path.join("logs", "ram.bin")
    if os.path.exists(ram):
        dados = open(ram, "rb").read()
        textos = [m.group().decode() for m in re.finditer(rb"[\x20-\x7e\t]{8,}", dados)]
        with open(os.path.join("logs", "ram_texto.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(textos))
        pistas = [t for t in textos if PISTAS.search(t)]
        with open(os.path.join("logs", "ram_pistas.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(pistas))
        print(f"\n== RAM: {len(dados)} bytes lidos, {len(textos)} trechos de texto, {len(pistas)} pistas")
        for t in pistas[-25:]:
            print(f"   {t[:150]}")
        print("   (completo em logs\\ram_texto.txt e logs\\ram_pistas.txt)")
    return 0


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("preparar", "analisar"):
        print(__doc__)
        return 1
    return {"preparar": preparar, "analisar": analisar}[sys.argv[1]](sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    sys.exit(main())
