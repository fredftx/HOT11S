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

## Histórico de tentativas
- **14/10/2026:** gravado o `boot.img` da ROM `Infinix_Hot_11S_NFC_X6812B_MT6768_V347_20210927`
  em `boot_a` e `boot_b` (100%, sem erro). Resultado: LED aceso direto, tela preta e não liga.
  Causa provável: a V347 é de **set/2021** e o resto do aparelho (LK de 06/05/2022) é mais
  novo. O kernel antigo não combina com o vendor e o super mais novos.
  **Próximo passo:** usar uma ROM de 05/2022 ou mais nova, de preferência a mais recente
  da mesma região, e gravá-la **inteira**, sem as partições de IMEI.
- **14/10/2026:** baixada a ROM `Infinix_Hot_11S_NFC_X6812B_MT6768_OP_V1218_241128` (nov/2024).
  Criada a **opção 9** (`tools/gravar_rom.py`). Ela monta um plano, pula as partições de
  IMEI, o preloader e os dados do usuário, grava cada imagem nos slots A e B e desempacota
  imagens sparse. Antes de gravar, confere se o slot ativo combina com o `super.img`.
- **14/10/2026:** plano da V1218 conferido. Todos os tamanhos batem com o aparelho, mas o
  `super.img` só tem sistema no **slot A** (`system_a`, `vendor_a`, `product_a`,
  `system_ext_a`; os `_b` estão vazios). O `misc` (controle A/B padrão do Android, offset 0x800,
  CRC conferido) mostra prioridade A=14 e B=15, ou seja, o aparelho está no **slot B**.
  A opção 9 agora também grava `backup\misc_slot_a.bin`, uma cópia do `misc` em que só mudam
  as prioridades (A=15, B=14) e o CRC.
- **14/10/2026:** a gravação do `super` (7 GB) caía no meio e a opção 9 recomeçava do zero,
  porque só pulava partições inteiras. Corrigido: o `super` agora é dividido em pedaços de 256 MB,
  gravados com `wo` numa única conexão (`mtk.py script`). Cada pedaço confirmado é anotado na
  hora em `logs\rom_gravadas.txt`, e a próxima rodada continua do pedaço seguinte.
- **14/10/2026:** ROM V1218 gravada até 100% (slot A ativo). Continua em bootloop, agora mais
  curto: o Preloader aparece a cada ~23 s, contra ~68 s antes. O `expdb` relido às 13:55 só tem
  o kernel antigo (TWRP, slot B), sem nenhuma linha das inicializações novas, e os registros
  do LK de antes sumiram. Ou seja, o kernel novo nunca chegou a rodar e o travamento está no LK
  ou no TEE/ATF. Suspeita principal: o **preloader de 2022**, mantido por segurança, não
  combina com o `lk`/`tee` de 2024. Criada a **opção 10**: ela lê o preloader atual (boot1),
  compara com o da ROM e grava o da ROM.
- **14/10/2026:** opção 10, leitura OK. O preloader do aparelho é de **2022-08-23**, o da V1218
  é de **2024-11-27**. O arquivo da ROM vem sem o cabeçalho `EMMC_BOOT`/`BRLYT` da área boot1,
  então a ferramenta agora monta a imagem: o cabeçalho do próprio aparelho, com o campo de
  fim do preloader no `BRLYT` atualizado, mais o preloader da ROM.
- **14/10/2026:** o `BRLYT` real reserva uma área fixa para o preloader (0x800–0x80800, 512 KB),
  e não o tamanho exato. O preloader da V1218 (309036 bytes) cabe nela, então o cabeçalho fica
  igual. A opção 10 agora lê o descritor `BBBB` diretamente.
- **14/10/2026:** preloader da V1218 gravado. O ciclo continua igual (Preloader a cada ~28 s).
  Criada a **opção 11** (só leitura): numa conexão, lê 16 MB da RAM a partir de 0x4d000000
  (onde fica o pstore/ramoops do kernel) e o primeiro 1 MB de `lk`, `boot`, `tee`, `vbmeta`,
  `super` e `misc`, e compara com a ROM.
- **14/10/2026:** o aparelho parou de aparecer no USB (nem Preloader nem BROM). Fica uma luz
  branca acesa perto da câmera frontal, que **apaga na hora quando o cabo é desconectado**.
  Ou seja, o aparelho funciona só com a energia do cabo. A suspeita é de bateria descarregada
  a nível crítico (pré-carga do preloader) ou bateria sem segurar carga.
  **Próximo passo:** 2 a 3 h no carregador de tomada, sem mexer. Se a luz continuar apagando na
  hora sem o cabo, trocar a bateria. As gravações (V1218, slot A, preloader novo) continuam
  no aparelho.
- **14/10/2026:** depois de 2 a 3 h no carregador de tomada, nada mudou: a luz não muda e apaga
  na hora sem o cabo. Nem o BROM aparece no USB. Conclusão: a **bateria não está recebendo nem
  segurando carga** (descarga profunda com a proteção desligada, ou bateria com defeito).
  **Próximo passo:** carregar a noite toda com outro carregador e outro cabo. Se continuar igual,
  testar ou trocar a bateria numa assistência, sem regravar firmware. Depois, rodar o
  `INICIAR-DIAGNOSTICO.bat` e a opção 11. Parte do bootloop pode ter sido causada pela própria
  bateria fraca.
