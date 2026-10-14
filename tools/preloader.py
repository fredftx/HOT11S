"""Compara o preloader gravado no aparelho com o da ROM e prepara a gravacao.

Uso: python preloader.py <pasta_da_rom> <preloader_atual.bin> <saida.bin>

O preloader da ROM vem "puro" (comeca com MMM). Na area boot1 ele fica depois de um
cabecalho EMMC_BOOT + BRLYT que diz onde ele comeca e termina. Este script monta em
<saida.bin> o cabecalho do proprio aparelho, com o fim corrigido, + o preloader da ROM,
e sai com 0 se a imagem pode ser gravada no boot1.
"""
import os
import re
import struct
import sys

LIMITE = 4 * 1024 * 1024  # tamanho da area boot1 do eMMC


def achar(pasta):
    for raiz, _, arquivos in os.walk(pasta):
        for nome in arquivos:
            if nome.lower().startswith("preloader") and nome.lower().endswith(".bin"):
                return os.path.join(raiz, nome)
    return None


def descrever(rotulo, dados):
    print(f"== {rotulo}: {len(dados)} bytes, comeca com {dados[:9]!r}")
    vistos = []
    for m in re.finditer(rb"[\x20-\x7e]{6,}", dados):
        s = m.group().decode()
        if re.search(r"20[12]\d[01]\d[0-3]\d|x6812|h6912|V\d{3}", s) and s not in vistos:
            vistos.append(s)
    for s in vistos[:8]:
        print(f"   {s[:100]}")
    if not vistos:
        print("   (nenhuma data/versao encontrada)")


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 1
    rom = achar(sys.argv[1])
    if not rom:
        print(f"[ERRO] Nenhum preloader*.bin dentro de {sys.argv[1]}")
        return 1
    novo = open(rom, "rb").read()
    atual = open(sys.argv[2], "rb").read() if os.path.exists(sys.argv[2]) else b""

    if atual:
        descrever("Preloader no aparelho hoje", atual.rstrip(b"\0"))
    descrever(f"Preloader da ROM ({os.path.basename(rom)})", novo)

    if not atual.startswith(b"EMMC_BOOT"):
        print("[ERRO] Nao consegui ler o preloader atual (backup vazio ou invalido). Tente de novo.")
        return 1
    imagem = montar_imagem(atual, novo)
    if imagem is None:
        return 1
    if atual[:len(imagem)] == imagem:
        print("[INFO] O preloader do aparelho JA E IGUAL ao da ROM. Nao precisa gravar.")
        return 1
    with open(sys.argv[3], "wb") as f:
        f.write(imagem)
    print(f"\n[OK] Imagem montada ({len(imagem)} bytes). Pode ser gravada no boot1.")
    return 0


def tamanho_gfh(dados, inicio):
    """Tamanho do preloader segundo o proprio cabecalho GFH (campo em MMM+0x20)."""
    if dados[inicio:inicio + 4] != b"MMM\x01":
        return None
    return struct.unpack_from("<I", dados, inicio + 0x20)[0]


def montar_imagem(atual, novo):
    brlyt = struct.unpack_from("<I", atual, 0x10)[0]
    if atual[brlyt:brlyt + 5] != b"BRLYT":
        print("[ERRO] Nao achei o BRLYT no preloader atual. NAO grave.")
        return None
    inicio = struct.unpack_from("<I", atual, brlyt + 0xC)[0]
    tam_velho = tamanho_gfh(atual, inicio)
    if novo.startswith(b"EMMC_BOOT"):
        print("[ERRO] O preloader da ROM ja tem cabecalho EMMC_BOOT; caso nao previsto. NAO grave.")
        return None
    tam_novo = tamanho_gfh(novo, 0)
    if tam_velho is None or tam_novo is None:
        print("[ERRO] Cabecalho MMM do preloader nao reconhecido. NAO grave.")
        return None
    if tam_novo != len(novo):
        print(f"[ERRO] Tamanho no cabecalho ({tam_novo}) != tamanho do arquivo ({len(novo)}). NAO grave.")
        return None
    print(f"\n   cabecalho: BRLYT em 0x{brlyt:x}, preloader comeca em 0x{inicio:x}")
    print(f"   tamanho do preloader: atual {tam_velho} bytes, ROM {tam_novo} bytes")
    print(f"   BRLYT atual: {atual[brlyt:brlyt + 0x30].hex(' ')}")

    cabecalho = bytearray(atual[:inicio])
    # o BRLYT guarda o fim do preloader (exato ou alinhado); troca pelo fim do novo
    trocas = []
    for alinhar in (1, 0x200, 0x1000):
        fim_velho = -(-(inicio + tam_velho) // alinhar) * alinhar
        fim_novo = -(-(inicio + tam_novo) // alinhar) * alinhar
        for pos in range(brlyt, len(cabecalho) - 3, 4):
            if struct.unpack_from("<I", cabecalho, pos)[0] == fim_velho and pos not in [t[0] for t in trocas]:
                trocas.append((pos, fim_velho, fim_novo))
    if len(trocas) != 1:
        print(f"[ERRO] Esperava 1 campo de fim do preloader no BRLYT, achei {len(trocas)}. "
              "NAO grave; mande este print para o Claude.")
        return None
    pos, fim_velho, fim_novo = trocas[0]
    struct.pack_into("<I", cabecalho, pos, fim_novo)
    print(f"   fim do preloader no BRLYT (0x{pos:x}): 0x{fim_velho:x} -> 0x{fim_novo:x}")

    imagem = bytes(cabecalho) + novo
    # apaga as sobras do preloader antigo, se o novo for menor
    fim_total = max(inicio + tam_velho, len(imagem))
    imagem = imagem.ljust(-(-fim_total // 0x200) * 0x200, b"\0")
    if len(imagem) > LIMITE:
        print("[ERRO] A imagem montada e maior que a area boot1. NAO grave.")
        return None
    return imagem


if __name__ == "__main__":
    sys.exit(main())
