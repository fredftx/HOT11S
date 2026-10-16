# HOT11S – recuperação de um Infinix Hot 11S em bootloop

Projeto do usuário para recuperar o próprio celular. **Toda a conversa e os textos para o
usuário são em português (pt-BR)**, sem jargão desnecessário. O usuário roda tudo no
**Windows**, na pasta `D:\CLAUDE PROJECTS\HOT11S`, e envia logs e prints pelo GitHub (upload
pela web no `main`) ou direto no chat. O Claude não tem acesso ao celular: só vê o que o
usuário envia.

Histórico detalhado, com datas: `DIAGNOSTICO.md`. Este arquivo resume o estado e as regras
para continuar.

---

## Situação atual (16/10/2026)

**O problema agora é a bateria, não o software.**

- Fica uma luz branca acesa perto da câmera frontal enquanto há cabo conectado. Ela **apaga na
  hora quando o cabo sai**, mesmo depois de 2–3 h no carregador de tomada.
- Não aparece **nada** no USB: nem Preloader, nem BROM (com VOL+ e VOL- seguros).
- Conclusão: a bateria não recebe nem segura carga (descarga profunda com a proteção desligada,
  ou bateria com defeito). Pode ter contribuído para os bootloops.
- O `expdb` antigo (commit `c32281c`) já mostrava a bateria reconhecida (`bat is exist`), mas
  instável: 4,30 V → **3,37 V** dentro do mesmo boot, abaixo do limite de 3,4 V. Indica bateria
  desgastada, com resistência interna alta. Linhas úteis para procurar:
  `pl_check_bat_protect_status`, `get_bat_volt`, `boot_voltage`, `bat is exist`.
- **Próximo passo combinado:** carregar a noite toda com outro carregador e outro cabo. Se
  continuar igual, levar a uma assistência para **testar com fonte de bancada** e/ou **trocar a
  bateria** (modelo escrito na etiqueta da bateria atual). Pedir ao técnico para **não
  formatar nem regravar firmware**.
- O usuário perguntou sobre usar a bateria de um Samsung GT-P7500 (Galaxy Tab 10.1). Resposta:
  **não**. Formato e conector diferentes, tensão de carga diferente (4,2 V contra a do Hot 11S,
  provavelmente 4,4 V), ~15 anos de idade, ID de bateria diferente e risco de incêndio.

**Quando o aparelho voltar a ter energia:**
1. `INICIAR-DIAGNOSTICO.bat` para ver se o ciclo voltou (Preloader a cada ~28 s) ou se liga.
2. Se ainda houver bootloop, **opção 11** (diagnóstico pós-gravação, só leitura) para
   conferir se a gravação bate com a ROM e tentar ler o ramoops da RAM.
3. Analisar o resultado antes de gravar qualquer coisa nova.

---

## Aparelho

| Item | Valor |
|---|---|
| Modelo | Infinix Hot 11S **NFC**, X6812B (projeto `x6812_h6912`) |
| SoC | MT6768 / Helio G88 (`hwcode 0x707`, "MT6769H" no kernel) |
| Armazenamento | eMMC Samsung 128 GB (`3V6CAB`), boot1/boot2 de 4 MB |
| Android | 11, A/B (slots `_a` / `_b`), super dinâmico, boot header v2 |
| Segurança | SBC ligado, SLA desligado, DAA ligado; mtkclient entra via **kamakiri (BROM)** |
| Bootloader | **desbloqueado** (`verifiedbootstate=orange`) |
| Bateria (log antigo) | `Battery id (2)`, carregador `rt9471` |

`hwparam.json` tem `meid`, `socid` e `cid` (gerado pelo mtkclient).

### Partições relevantes (offsets em bytes, de `particoes.txt`)
| Partição | Offset | Tamanho |
|---|---|---|
| misc | 0x1d08000 | 0x80000 |
| expdb | 0x1e08000 | 0x1400000 |
| vbmeta_a | 0x3308000 | 0x800000 |
| nvcfg / nvdata / persist / protect1 / protect2 / nvram | — | **IMEI/calibração – nunca gravar** |
| lk_a / lk_b | 0x1e000000 / 0x33800000 | 0x200000 |
| boot_a / boot_b | 0x1ea00000 / 0x34200000 | 0x2000000 (32 MB) |
| vendor_boot_a/_b | 0x20a00000 / 0x36200000 | 0x4000000 (vazias, normal no header v2) |
| tee_a | 0x25200000 | 0x600000 |
| super | 0x3b000000 | 0x1b5d7a000 (~7 GB) |
| userdata | 0x204000000 | ~108 GB |

Setor = 512 bytes (`boot_a` = setor 1003520; `misc` = setor 59456).

---

## O que foi descoberto e feito (em ordem)

1. **Causa original do bootloop:** o `boot` (nos dois slots) tinha uma imagem **TWRP/modificada**
   (`twrpfastboot=1 buildvariant=eng`, patch `2099-12`, ramdisk LZMA corrompido).
   O `expdb` mostrava `Kernel panic - not syncing: Could not decompress initial ramdisk image`
   a ~0,6 s, sempre no slot B, com reinício pelo watchdog (ciclo de ~68 s).
2. **boot.img da V347 (set/2021) gravado** nos dois slots (opção 8) → tela preta e luz acesa.
   A V347 era **mais antiga** que o resto do aparelho (LK de 06/05/2022). Lição: não misturar
   versões. Gravar a ROM inteira de uma versão só.
3. **ROM `Infinix_Hot_11S_NFC_X6812B_MT6768_OP_V1218_241128` (nov/2024, OP/global) gravada
   inteira** (opção 9): vbmeta*, md1img, spmfw, scp, sspm, gz, lk, logo, boot, dtbo, tee nos
   dois slots, e o super. Ficaram de fora: preloader (na época), nvram/nvdata/nvcfg/proinfo/
   protect1/protect2/persist/seccfg/otp/flashinfo/frp/sec1/md_udc, userdata, metadata, expdb,
   boot_para, para, misc (só o slot foi trocado) e tranfs.
4. **Slot A ativado:** o `super.img` da ROM só tem `system_a/vendor_a/product_a/system_ext_a`
   (os `_b` têm 0 MB). O `misc` usa o `bootloader_control` padrão do AOSP (magic `BCAB` em
   0x800, CRC32 nos 28 primeiros bytes, conferido). Original: A=14 e B=15 → slot B ativo.
   Gravada uma cópia com A=15 e B=14 (só 4 bytes mudam):
   `00 00 00 00 42 43 41 42 01 02 00 00 9f 00 9e 00 … 3c 65 42 ca`.
5. **Resultado:** continuou em bootloop, mais curto (Preloader a cada ~23–28 s). O `expdb`
   relido não tinha nenhuma linha das novas inicializações: o kernel novo nunca rodou, então
   o travamento seria no LK ou no TEE/ATF.
6. **Preloader da V1218 gravado** (opção 10). Era de 2022-08-23, agora 2024-11-27. O arquivo da
   ROM vem "puro" (`MMM\x01…`). No boot1 ele fica depois do cabeçalho `EMMC_BOOT` (0x0) +
   `BRLYT` (0x200). No aparelho, o `BRLYT` reserva uma **área fixa** de 0x800 a 0x80800
   (descritor `BBBB`, dispositivo 5, tipo 1); o cabeçalho não muda. Backup do original:
   `backup\preloader_boot1_atual.bin`.
   Resultado: o ciclo continuou igual (~28 s).
7. **Opção 11 criada** (RAM + conferência), mas não chegou a conectar: o aparelho parou de
   aparecer no USB → bateria (ver "Situação atual").

**Estado gravado no aparelho agora:** ROM V1218 completa, preloader V1218, slot A ativo,
IMEI/calibração e userdata originais intocados.

---

## Arquivos do repositório

| Arquivo | Para quê |
|---|---|
| `FERRAMENTA-MTK.bat` | Menu principal (mtkclient + venv em `tools\`). Opções abaixo |
| `INICIAR-DIAGNOSTICO.bat` + `diagnostico-usb.ps1` | Monitora o USB e registra em que modo o celular aparece (BROM `0E8D:0003`, Preloader `0E8D:2000`, fastboot, ADB, MTP) |
| `tools/verificar_bootimg.py` | Valida um boot.img (cabeçalho, versão, TWRP, ramdisk descompacta) |
| `tools/gravar_rom.py` | Plano e gravação da ROM inteira (opção 9) |
| `tools/preloader.py` | Compara e monta a imagem boot1 com o preloader da ROM (opção 10) |
| `tools/verificar_gravacao.py` | Diagnóstico pós-gravação (opção 11) |
| `DIAGNOSTICO.md` | Histórico datado de cada tentativa |
| `particoes.txt`, `leitura_*.txt`, `boot_leitura.txt` | Saídas do mtkclient (**UTF-16 LE** com códigos ANSI; ler com `iconv -f UTF-16`) |
| `expdb_texto.txt`, `expdb_pistas.txt` | Texto extraído do expdb (o enviado às 13:55 só tem o kernel TWRP antigo) |
| `diagnostico-*.log` | Logs do monitor USB |

**Não estão no repo**, só no PC do usuário: `tools\venv`, `tools\mtkclient-main`,
`tools\analisar_boot.py`, `tools\analisar_logs.py`, `tools\verificar_nvdata.py`, `backup\`,
`firmware\` e `logs\`. O `.gitignore` bloqueia `backup/`, `*.bin`, `firmware/`, `tools/venv/`,
`tools/mtkclient-main/` e `__pycache__/`.

### Menu do `FERRAMENTA-MTK.bat`
1. Informações + tabela de partições → `logs\particoes.txt` (só leitura)
2. Backup das partições essenciais (IMEI etc.) → `backup\`
3. GUI do mtkclient
4. **Reset de fábrica** (apaga userdata e metadata, pede `APAGAR`)
5. Reler o nvdata e verificar se está vazio (só leitura)
6. Ler o expdb e o misc e analisar (só leitura)
7. Ler as imagens de boot A/B, uma partição por vez, retomando de onde parou (só leitura)
8. Gravar `firmware\boot.img` em boot_a e boot_b (verifica antes, pede `GRAVAR`)
9. Gravar a ROM inteira de `firmware\rom\` (plano em `logs\plano_rom.txt`, pede `GRAVAR`)
10. Gravar o preloader da ROM no boot1 (lê o atual, compara, monta, pede `GRAVAR`)
11. Diagnóstico pós-gravação: `da peek` de 16 MB da RAM em 0x4d000000 (ramoops em 0x4d010000)
    + `ro` do primeiro 1 MB de lk/boot/tee/vbmeta/super/misc, comparando com a ROM
    (saída do mtkclient em `logs\verif_mtk.txt`)
12. Sair

### Detalhes da opção 9 (`gravar_rom.py`)
- Lê o scatter (`MT6768_Android_scatter.txt`) e a tabela de partições. Recusa se algum tamanho
  diferir. Cada imagem de slot vai para `_a` **e** `_b`.
- Imagens sparse são desempacotadas em `firmware\raw\` (via `.tmp` + rename).
- Partições acima de 512 MB (o super) são divididas em **pedaços de 256 MB**
  (`firmware\raw\super.img.partes\NNN.bin`, divididas do fim para o começo encolhendo o `.raw`)
  e gravadas com `wo <offset> <tam> <arquivo>` numa única conexão (`mtk.py script`).
- Progresso salvo **na hora** em `logs\rom_gravadas.txt` (`lk_a`, `super#012`…), detectado
  pelas linhas `Wrote … to sector N` (w) e `Wrote … to offset 0x…` (wo).
- Bloqueia se o super só tiver o slot A e o `misc` não indicar o A ativo; nesse caso gera
  `backup\misc_slot_a.bin` e o grava junto.

---

## Regras de segurança (não negociáveis)

- **Nunca gravar nem apagar** nvram, nvdata, nvcfg, proinfo, protect1, protect2, persist,
  seccfg, otp ou flashinfo (IMEI e calibração). Backup em `backup\` (só no PC).
- **Nunca pedir ao usuário para enviar `backup\`** nem arquivos com IMEI ao GitHub.
  boot.img, logs de texto e prints podem ir.
- Toda gravação: mostrar plano/verificação → pedir ao usuário um print **antes** de digitar
  `GRAVAR` quando houver dúvida → só então gravar. Scripts abortam se algo não bater.
- Não gravar o preloader "puro" direto no boot1 (precisa do cabeçalho EMMC_BOOT/BRLYT).
- O BROM fica no chip e sempre permite recuperar, **desde que o aparelho tenha energia**.

## Pegadinhas já encontradas

- **Entrar no BROM:** o BROM só confere os botões **ao reiniciar**. Funciona desconectar e
  reconectar o cabo segurando VOL+ e VOL-, ou ficar segurando até a próxima reinicialização
  do ciclo. Com o aparelho travado, POWER+VOL+ e VOL- por 10–20 s.
  Os erros `USB enumeration error … Other error` antes de conectar são ruído (UsbDk vendo
  outros aparelhos ou o Preloader sem driver).
- O mtkclient usa UsbDk (`MTK_USBDK=1`). O Preloader aparece **sem driver** no Windows (normal).
- Leituras e gravações longas caem por USB (`USBError(5)`): sempre dividir e permitir retomar.
- `mtk.py script`/`multi` separa os argumentos por espaço → **caminhos sem espaço** (usar
  relativos; a pasta do usuário tem espaço).
- `mtk w` com `--parttype boot1` grava a partir do offset 0 do boot1. `r preloader x.bin
  --parttype boot1` lê os 4 MB.
- Em `.bat`, **não usar parênteses dentro de `echo` dentro de blocos `if (...)`**; isso quebra
  o bloco. O `.bat` está com quebras de linha LF; se surgir problema com `goto`/`call`,
  converter para CRLF.
- O `expdb` só ganha registros novos quando o kernel roda e salva. Sem registro novo, o
  travamento é antes do kernel (ou o kernel nem iniciou).
- Saídas do mtkclient salvas pelo PowerShell (`Tee-Object`) são UTF-16.

## Fluxo de trabalho no git

- Branch de trabalho: `claude/fix-mobile-device-94i12g`. O usuário faz merge para o `main`
  pela web e envia arquivos direto no `main` ("Add files via upload"). Antes de trabalhar:
  `git fetch origin` e trazer o `main` para a branch.
- Commits em português, descrevendo o porquê. Atualizar o `DIAGNOSTICO.md` a cada tentativa.
- Testar scripts Python localmente com dados simulados (ROM falsa, mtk.py falso que escreve
  num `flash.bin`) antes de entregar. O `.bat` não pode ser testado no Linux.
