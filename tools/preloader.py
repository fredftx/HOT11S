"""Compara o preloader gravado no aparelho com o da ROM e prepara a gravacao.

Uso: python preloader.py <pasta_da_rom> <preloader_atual.bin> <saida.bin>
Copia o preloader da ROM para <saida.bin> e sai com 0 se ele pode ser gravado no boot1.
"""
import os
import re
import shutil
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

    if not novo.startswith(b"EMMC_BOOT"):
        print("[ERRO] O preloader da ROM nao comeca com o cabecalho EMMC_BOOT. NAO grave.")
        return 1
    if len(novo) > LIMITE:
        print("[ERRO] O preloader da ROM e maior que a area boot1. NAO grave.")
        return 1
    if not atual.startswith(b"EMMC_BOOT"):
        print("[ERRO] Nao consegui ler o preloader atual (backup vazio ou invalido). Tente de novo.")
        return 1
    if atual[:len(novo)] == novo:
        print("[INFO] O preloader do aparelho JA E IGUAL ao da ROM. Nao precisa gravar.")
        return 1

    shutil.copyfile(rom, sys.argv[3])
    print("\n[OK] Os preloaders sao diferentes. O da ROM pode ser gravado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
