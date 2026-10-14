"""Confere se um boot.img serve para o Infinix Hot 11S (X6812B) antes de gravar.

Uso: python verificar_bootimg.py <boot.img>
Sai com codigo 0 se o arquivo parece bom, 1 se nao deve ser gravado.
"""
import lzma
import struct
import sys
import zlib

PARTICAO = 32 * 1024 * 1024  # boot_a/boot_b tem 32 MB


def alinhar(n, page):
    return (n + page - 1) // page * page


def tipo_compressao(dados):
    if dados[:4] == b"\x02\x21\x4c\x18" or dados[:4] == b"\x04\x22\x4d\x18":
        return "lz4"
    if dados[:2] == b"\x1f\x8b":
        return "gzip"
    if dados[:3] == b"\x5d\x00\x00" or dados[:6] == b"\xfd7zXZ\x00":
        return "lzma"
    return "desconhecida"


def testar_ramdisk(comp, dados):
    """Tenta descompactar o ramdisk inteiro, como o kernel faz no boot."""
    try:
        if comp == "gzip":
            zlib.decompress(dados, 16 + zlib.MAX_WBITS)
        elif comp == "lzma":
            lzma.decompress(dados)
        else:
            return None  # lz4 nao tem modulo padrao no Python; so confere o cabecalho
        return True
    except Exception as e:  # noqa: BLE001
        print(f"   erro ao descompactar: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    caminho = sys.argv[1]
    with open(caminho, "rb") as f:
        img = f.read()

    print(f"== {caminho}  {len(img)} bytes")
    if img[:8] != b"ANDROID!":
        print("   NAO E um boot.img Android (falta 'ANDROID!' no inicio). NAO GRAVE.")
        return 1
    if len(img) > PARTICAO:
        print("   Maior que a particao boot (32 MB). NAO GRAVE.")
        return 1

    kernel_size, _, ramdisk_size = struct.unpack_from("<III", img, 8)
    page = struct.unpack_from("<I", img, 36)[0] or 2048
    os_version = struct.unpack_from("<I", img, 44)[0]
    versao = os_version >> 11
    patch = os_version & 0x7FF
    android = f"{versao >> 14}.{(versao >> 7) & 0x7F}.{versao & 0x7F}"
    patch_txt = f"{2000 + (patch >> 4)}-{patch & 0xF:02d}"
    header_version = struct.unpack_from("<I", img, 40)[0]
    cmdline = img[64:64 + 512].split(b"\0")[0].decode("ascii", "replace")

    print(f"   header v{header_version}, kernel {kernel_size} bytes, ramdisk {ramdisk_size} bytes")
    print(f"   Android {android}, patch {patch_txt}")
    print(f"   cmdline: {cmdline or '(vazia)'}")

    problemas = []
    if "twrp" in cmdline.lower() or patch_txt.startswith("2099"):
        problemas.append("parece TWRP/imagem modificada (cmdline com twrp ou patch 2099) - e o mesmo tipo de imagem que esta travando o aparelho")
    if android.split(".")[0] != "11":
        problemas.append(f"o aparelho roda Android 11, esta imagem e Android {android}")

    inicio_ramdisk = page + alinhar(kernel_size, page)
    ramdisk = img[inicio_ramdisk:inicio_ramdisk + ramdisk_size]
    if len(ramdisk) < ramdisk_size:
        problemas.append("arquivo cortado: o ramdisk termina antes do esperado")
    else:
        comp = tipo_compressao(ramdisk)
        print(f"   compressao do ramdisk: {comp}")
        ok = testar_ramdisk(comp, ramdisk)
        if ok is False:
            problemas.append("o ramdisk esta corrompido (e exatamente o erro do bootloop atual)")
        elif ok is True:
            print("   ramdisk descompactou sem erros")

    if problemas:
        for p in problemas:
            print(f"   [PROBLEMA] {p}")
        print("   NAO GRAVE este arquivo.")
        return 1
    print("   [OK] Parece um boot.img de estoque valido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
