# Diagnóstico – Infinix Hot 11S (X6812B)

## Aparelho
- SoC MT6768 (hwcode 0x707), eMMC Samsung 128 GB (3V6CAB), Android 11, slots A/B.
- LK de 06/05/2022 (`LK_VER_TAG = x6812_h6912-...-20220506200314`), kernel 4.14.186.
- Bootloader **desbloqueado** (`device_state=unlocked`, `verifiedbootstate=orange`).
- O BROM/mtkclient funcionam: dá para ler e gravar qualquer partição.

## Causa do bootloop
Fonte: `expdb_pistas.txt` / `expdb_texto.txt`, gerados pela opção 6.

```
RAMDISK: lzma image found at block 0
RAMDISK: lzma decompressing
Kernel panic - not syncing: Could not decompress initial ramdisk image.
```

- O kernel trava em **~0,6 s** em todas as tentativas (7 vezes no log), sempre no **slot B**.
  Depois o watchdog reinicia o aparelho, e é por isso que o Preloader aparece e some a cada ~1 min.
- A imagem `boot` gravada **não é a de estoque**. A cmdline tem `twrpfastboot=1 buildvariant=eng`
  e o cabeçalho mostra patch `2099-12`, o padrão de imagens TWRP ou modificadas.
  O ramdisk dela (LZMA, 16,7 MB) está corrompido ou incompleto.
- O `boot_a` tem o mesmo cabeçalho (mesmos tamanhos de kernel e ramdisk), então
  **trocar de slot não resolve**.
- `nvdata`, `nvram` e o resto do sistema não aparecem como causa. O travamento acontece
  antes de o Android montar qualquer partição.

Obs.: o `boot_analise.txt` dizia "ARQUIVO INCOMPLETO". Isso era só a leitura pelo USB que
caía no meio. A última leitura do `boot_b` chegou a 100% (`leitura_boot_b.txt`).

## Conserto
1. Baixar a ROM de estoque do **X6812B** (Android 11, de preferência a mesma versão ou mais
   nova que a de maio/2022) e tirar dela o `boot.img`.
2. Colocar em `firmware\boot.img` (na pasta da ferramenta) e rodar a **opção 8** do
   `FERRAMENTA-MTK.bat`. Ela confere o arquivo com `tools\verificar_bootimg.py` e grava em
   `boot_a` e `boot_b`. Não apaga dados nem o IMEI.
3. Se ligar mas ficar preso no logo do Infinix, faltam outras partições da mesma ROM
   (`vbmeta`, `vendor_boot`, `dtbo`). Em último caso, gravar a ROM inteira pelo SP Flash Tool em
   modo **Download Only**, com `nvram`, `nvdata`, `proinfo`, `protect1` e `protect2` **desmarcados**.

**Nunca** enviar a pasta `backup\` para o GitHub (tem o IMEI).
