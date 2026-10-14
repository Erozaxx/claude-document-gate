# Claude Document Gate

English: [README.md](README.md)

Hook pro Claude Code, který dokument převede na Markdown přímo u vás v počítači, ještě než ho uvidí model.

Když prompt odkazuje na soubor PDF, DOCX, PPTX, XLSX nebo EPUB, hook ho nejdřív zastaví. Soubor lokálně převede přes [Microsoft MarkItDown](https://github.com/microsoft/markitdown), text prožene jednoduchou regex sanitizací a uloží čistou kopii `.md`. Model pak dostane váš původní požadavek, jen místo cesty k souboru v něm je cesta k té kopii.

Soubory HTML, CSV, TXT a MD jde zapnout v [konfiguraci](#konfigurace). Ve výchozím stavu jsou vypnuté, aby hook nepřesměrovával běžné soubory v projektu, třeba README. U prostého textu převod tokeny neušetří.

Hook je malý program, který Claude Code spouští automaticky v určitou chvíli. Tenhle běží při každém odeslaném promptu, dřív než ho dostane model.

## Proč

Hlavní důvod je spotřeba tokenů. Model čte prostý text a nemusí zpracovávat PDF nebo soubor z Office, což bývá výrazně dražší.

Druhý efekt je základní maskování některých citlivých údajů. Ve výchozím stavu je zapnuté a jde vypnout. Sanitizace nahradí e-mailové adresy, IPv4 adresy, telefonní čísla, IBAN, rodná čísla, Bearer tokeny a vybrané API klíče značkami typu `[REDACTED_EMAIL_3f2a91c0d4]`.

Maskování je vedlejší přínos. Nenahrazuje DLP nástroj ani anonymizaci. Nepozná jména, adresy, firemní identifikátory ani text v obrázcích.

## Jak to funguje

```
Odešlete prompt
   |
   v
hook.py běží u vás v počítači, model zatím nic neviděl
   |
   +-- v promptu není existující soubor s nastavenou příponou
   |     -> prompt jde k modelu beze změny
   |
   +-- existující dokument nalezen
         |
         +-- blokovaný formát, moc velký, po převodu prázdný
         |   nebo chyba konfigurace
         |     -> prompt zablokován, uvidíte důvod
         |
         +-- jinak
               1. MarkItDown převede soubor na Markdown
               2. regex sanitizace zamaskuje e-maily, telefony, IBAN...
                  (jde vypnout)
               3. kopie se uloží jako sanitized_<název>_<hash>.md
                  (bez sanitizace converted_<název>_<hash>.md)
               4. původní prompt se zablokuje
               5. hook pošle přepsaný prompt do stejné session
               6. model pracuje s kopií .md
```

Příklad na Windows. Napíšete:

```text
Shrň mi "C:\Users\me\Documents\report.pdf"
```

Claude Code ukáže, že původní prompt byl zablokovaný, a vypíše cestu k sanitizované kopii. Model pak dostane zprávu zhruba takovou:

```text
[DOCUMENT_GATE: SANITIZED]
Original user request (all detected document references have been replaced by validated sanitized references):
Shrň mi "C:\Users\me\local_app\claude_document_gate\sanitized\sanitized_report_9b1c47e0a2d3.md"

Validated local sanitized files:
- "C:\Users\me\local_app\claude_document_gate\sanitized\sanitized_report_9b1c47e0a2d3.md"

The original attachment was blocked BEFORE this turn. Only use the sanitized files above; ...
```

Text zprávy je anglicky, protože ho čte model. Upravit ho jde v `session_message.json`.

V sanitizované kopii se z řádku `Kontakt: jana.novakova@example.com, +420 731 456 789` stane:

```text
Kontakt: [REDACTED_EMAIL_3f2a91c0d4], [REDACTED_PHONE_8e07b5c219]
```

Stejná hodnota dostane na vašem počítači vždy stejnou značku. Model tak pozná, že dvě zmínky patří ke stejné adrese.

## Podporované platformy

| Platforma | Stav |
|---|---|
| Windows, Claude Code nainstalovaný přímo ve Windows | Podporováno |
| WSL (Ubuntu a další) a Linux | Podporováno |
| macOS | Připravuje se. Instalátor skončí s varováním, pokud nepřidáte `--allow-macos`. |

Hook funguje v Claude Code, tedy v nástroji pro příkazovou řádku. V chatu Claude.ai v prohlížeči ani v desktopovém chatu Claude nefunguje.

## Instalace na Windows

### 1. Nainstalujte Python

Potřebujete Python 3.10 až 3.14.

Možnost 1: stáhněte instalátor z [python.org](https://www.python.org/downloads/windows/). Na první obrazovce zaškrtněte **Add python.exe to PATH**.

Možnost 2: otevřete PowerShell a spusťte:

```powershell
winget install Python.Python.3.12
```

Zavřete PowerShell, otevřete nové okno a ověřte verzi:

```powershell
py -3 --version
```

### 2. Stáhněte projekt

Vyberte složku, kde projekt zůstane natrvalo, třeba `C:\Tools\claude-document-gate`. Claude Code bude hook spouštět z ní. Po instalaci ji nepřesouvejte.

Varianta A, přes git:

```powershell
git clone https://github.com/Erozaxx/claude-document-gate.git C:\Tools\claude-document-gate
```

Varianta B, bez gitu: otevřete https://github.com/Erozaxx/claude-document-gate, klikněte na zelené tlačítko **Code** a zvolte **Download ZIP**. Archiv rozbalte a rozbalenou složku `claude-document-gate-main` přejmenujte a přesuňte na `C:\Tools\claude-document-gate`.

### 3. Spusťte instalátor

```powershell
cd C:\Tools\claude-document-gate
py -3 install.py
```

Instalátor:

1. ověří verzi Pythonu,
2. vytvoří ve složce `.venv` samostatné prostředí Pythonu, takže nic neinstaluje do systému,
3. do něj nainstaluje `markitdown[all]` (potřebuje internet, může trvat pár minut),
4. ověří, že MarkItDown jde načíst, a spustí testy projektu,
5. vytvoří `config.json` z `config.default.json`, pokud ještě neexistuje,
6. teprve potom zapíše hook do nastavení Claude Code v `%USERPROFILE%\.claude\settings.json`.

Než `settings.json` změní, uloží vedle něj zálohu `settings.json.document-gate.bak`. Ostatní hooky a nastavení nechá, jak jsou. Opakované spuštění je bezpečné a hook nepřidá dvakrát.

Když selže krok 3 nebo 4, na `settings.json` se nesáhne.

### 4. Restartujte Claude Code a ověřte

Zavřete všechna běžící okna Claude Code a spusťte ho znovu. Napište `/hooks` a podívejte se na seznam hooků. Měl by tam být hook `UserPromptSubmit`, který ukazuje na `hook.py` ve složce projektu.

Pak to zkuste s libovolným PDF nebo souborem Wordu:

```text
Shrň mi "C:\Users\me\Documents\nejaky-soubor.pdf"
```

Měla by se objevit hláška, že původní prompt byl zablokovaný, a po ní odpověď modelu nad sanitizovanou kopií.

## Instalace na WSL nebo Linux

WSL a Windows jsou oddělená prostředí. Pokud Claude Code používáte v obou, nainstalujte hook do obou.

### 1. Nainstalujte Python

Na Ubuntu:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
python3 --version
```

Verze musí být 3.10 až 3.14.

### 2. Stáhněte projekt

Vyberte trvalou složku, třeba `~/tools/claude-document-gate`. Po instalaci ji nepřesouvejte.

Varianta A, přes git:

```bash
git clone https://github.com/Erozaxx/claude-document-gate.git ~/tools/claude-document-gate
```

Varianta B, bez gitu:

```bash
sudo apt install unzip wget
mkdir -p ~/tools
cd ~/tools
wget https://github.com/Erozaxx/claude-document-gate/archive/refs/heads/main.zip
unzip main.zip
mv claude-document-gate-main claude-document-gate
rm main.zip
```

### 3. Spusťte instalátor

```bash
cd ~/tools/claude-document-gate
python3 install.py
```

Kroky jsou stejné jako na Windows. Nastavení se zapíše do `~/.claude/settings.json`, případně do `$CLAUDE_CONFIG_DIR/settings.json`, pokud máte tu proměnnou nastavenou.

### 4. Restartujte Claude Code a ověřte

Restartujte Claude Code, napište `/hooks` a vyzkoušejte to na souboru:

```text
Shrň mi "/home/me/dokumenty/nejaky-soubor.pdf"
```

## Doporučené nastavení: vypnout zmínky souborů

Když napíšete `@soubor.pdf`, Claude Code může obsah souboru vložit do promptu sám, dřív než ho hook uvidí. Nastavte `CLAUDE_CODE_DISABLE_FILE_MENTIONS=1`. Pak `@cesta` zůstane obyčejným textem a hook ji zpracuje. Proměnnou zná Claude Code 2.1.299 a novější.

PowerShell, jen pro aktuální okno:

```powershell
$env:CLAUDE_CODE_DISABLE_FILE_MENTIONS = '1'
claude
```

PowerShell, trvale pro váš uživatelský účet (platí v nově otevřených oknech):

```powershell
setx CLAUDE_CODE_DISABLE_FILE_MENTIONS 1
```

bash, jen pro jedno spuštění:

```bash
CLAUDE_CODE_DISABLE_FILE_MENTIONS=1 claude
```

bash, trvale:

```bash
echo 'export CLAUDE_CODE_DISABLE_FILE_MENTIONS=1' >> ~/.bashrc
source ~/.bashrc
```

## Použití

Prompt pište jako obvykle a uveďte v něm cestu k souboru.

```text
Najdi všechny e-mailové adresy v docs/report.pdf
Co říká tahle smlouva o pokutách? "C:\Users\me\Documents\smlouva.docx"
Porovnej čísla v "Vysledky Q3.xlsx" a "Vysledky Q4.xlsx"
```

Cesty s mezerami dávejte do uvozovek. Bez nich hook nepozná, kde cesta končí.

Relativní cesty se počítají od složky, ve které Claude Code běží. Funguje i `@docs/report.pdf`, pokud máte vypnuté zmínky souborů.

Ve WSL můžete vložit cestu z Windows. Z `C:\Users\me\report.pdf` se stane `/mnt/c/Users/me/report.pdf`.

Ve výchozím stavu hook převádí `.pdf .docx .pptx .xlsx .epub` a blokuje přípony z další sekce. Ostatní typy souborů (třeba `.md`, `.json` nebo `.py`) ignoruje a prompt projde beze změny. Oba seznamy jde změnit v [konfiguraci](#konfigurace).

Když odkážete na sanitizovanou kopii, kterou hook vytvořil dřív, prompt projde beze změny. Hook předtím ověří podpis kopie.

Hook taky přeskakuje zprávy, které do session vkládá samotný Claude Code: oznámení o dokončených agentech na pozadí (`<task-notification>`), zprávy z jiných session (`<cross-session-message>`, „Another Claude session sent a message") a vlastní doručenou zprávu (`[DOCUMENT_GATE: SANITIZED]` nebo `[DOCUMENT_GATE: CONVERTED]`). Pozná je podle začátku textu.

## Kdy hook prompt zablokuje a nepošle dál

V těchto případech se prompt zablokuje, k modelu nejde nic a Claude Code ukáže důvod:

| Důvod | Co udělat |
|---|---|
| Soubor má příponu z `block_extensions`. Ve výchozím stavu `.doc .xls .ppt .zip .7z .png .jpg .jpeg .exe .bin` | Uložte soubor jako DOCX, XLSX, PPTX nebo PDF a zkuste to znovu. |
| Soubor má víc než 25 MiB | Dokument rozdělte nebo vyexportujte jen potřebnou část. |
| Převod nevrátil žádný text | Typicky skenované PDF bez textové vrstvy. Nejdřív na něj pusťte OCR v jiném nástroji. |
| Prompt odkazuje na existující dokument a má víc než 14 000 znaků nebo obsahuje vložený obsah | Pošlete kratší prompt a na soubor odkažte cestou. |
| Claude Code poslal soubor jako přílohu (obrázek, přetažení myší) | Napište do promptu cestu k souboru. |
| Prompt odkazuje na kopii `converted_` a sanitizace je zapnutá | Odkažte na původní dokument, hook ho převede znovu se sanitizací. |
| Chyba konfigurace, hláška začíná `Document gate config error:` | Opravte místo, které hláška uvádí: neplatný JSON, neznámý klíč, špatná hodnota v `config.json` nebo v proměnné prostředí. |

Dokud je konfigurace rozbitá, hook používá výchozí seznamy. Prompty bez existujícího souboru z těchto seznamů projdou, prompty s takovým souborem se zablokují.

Hook řeší jen soubory, které na disku existují. Prompt typu `Ulož shrnutí do shrnuti.docx` projde beze změny, když takový soubor ještě není, protože k modelu se nedostane žádný obsah dokumentu. V promptu s více cestami se existující soubory nahradí kopiemi a ostatní zůstanou jako text.

## Konfigurace

Nastavení je v souboru `config.json` ve složce projektu, třeba `C:\Tools\claude-document-gate\config.json` nebo `~/tools/claude-document-gate/config.json`. Instalátor ho vytvoří jako kopii `config.default.json`, pokud ještě neexistuje. Aktualizace ani další spuštění instalátoru ho nepřepíšou.

Výchozí obsah:

```json
{
  "convert_extensions": [".pdf", ".docx", ".pptx", ".xlsx", ".epub"],
  "block_extensions": [".doc", ".xls", ".ppt", ".zip", ".7z", ".png", ".jpg", ".jpeg", ".exe", ".bin"],
  "sanitize": true
}
```

Otevřete ho v libovolném textovém editoru:

```powershell
notepad C:\Tools\claude-document-gate\config.json
```

```bash
nano ~/tools/claude-document-gate/config.json
```

Hook čte konfiguraci při každém promptu. Změna v `config.json` platí od dalšího promptu, Claude Code není potřeba restartovat.

### Klíče

| Klíč | Výchozí hodnota | Význam |
|---|---|---|
| `convert_extensions` | `.pdf .docx .pptx .xlsx .epub` | Soubory, které se převádějí. Povolené hodnoty: `.pdf .docx .pptx .xlsx .html .htm .epub .csv .txt .md`. |
| `block_extensions` | `.doc .xls .ppt .zip .7z .png .jpg .jpeg .exe .bin` | Existující soubory s těmito příponami se zablokují bez převodu. Povolená je jakákoli přípona. |
| `sanitize` | `true` | `false` vypne maskování. Dokumenty se jen převedou na Markdown. |

Všechny klíče jsou nepovinné. Neznámý klíč je chyba konfigurace. Přípona uvedená v obou seznamech se blokuje. Soubor s příponou, která není v žádném seznamu, hook ignoruje a prompt projde beze změny.

### Proměnné prostředí

| Proměnná | Nahrazuje | Hodnota |
|---|---|---|
| `DOCUMENT_GATE_EXTENSIONS` | `convert_extensions` | Přípony oddělené čárkou, třeba `pdf,docx,md`. Tečka je nepovinná, na velikosti písmen nezáleží. |
| `DOCUMENT_GATE_BLOCK_EXTENSIONS` | `block_extensions` | Stejný formát. Prázdná hodnota neblokuje nic. |
| `DOCUMENT_GATE_SANITIZE` | `sanitize` | `1` nebo `0`, `true` nebo `false`, `on` nebo `off`, `yes` nebo `no`. |
| `DOCUMENT_GATE_HOME` | datová složka | Cesta ke složce, viz [Kam se ukládají soubory](#kam-se-ukládají-soubory). |

Pořadí priority od nejnižší: výchozí hodnoty v kódu, `config.default.json`, `config.json`, proměnné prostředí.

Proměnné prostředí dostává hook od Claude Code. Po nastavení nebo změně proměnné Claude Code restartujte.

### Příklad: převádět i soubory .md a .txt

V `config.json` změňte řádek `convert_extensions` na:

```json
  "convert_extensions": [".pdf", ".docx", ".pptx", ".xlsx", ".epub", ".md", ".txt"],
```

Od té chvíle hook zpracuje existující soubory `.md` a `.txt` v projektu stejně jako jiné dokumenty. Když napíšete `Oprav překlep v README.md`, model dostane místo originálu kopii.

### Příklad: jen převod, bez sanitizace

Pokud vám jde jen o tokeny, nastavte:

```json
  "sanitize": false
```

Kopie se pak jmenují `converted_<název>_<hash>.md`, zpráva pro model začíná `[DOCUMENT_GATE: CONVERTED]` a nemaskuje se ani text vašeho promptu. Když sanitizaci znovu zapnete, hook každý dokument při dalším odkazu převede znovu do kopie `sanitized_`.

Když je sanitizace zapnutá, hook zablokuje prompt, který odkazuje přímo na starou kopii `converted_`, protože ta maskovaná není. Odkažte místo ní na původní dokument a hook ho převede znovu se sanitizací.

### Příklad: nic neblokovat

V `config.json`:

```json
  "block_extensions": [],
```

Ve WSL nebo na Linuxu jde místo toho použít prázdnou proměnnou prostředí:

```bash
export DOCUMENT_GATE_BLOCK_EXTENSIONS=
```

Na Windows na to použijte `config.json`. Nástroje ve Windows prázdnou proměnnou často rovnou odstraní.

### Trvalé nastavení proměnné

PowerShell (platí v nově otevřených oknech):

```powershell
setx DOCUMENT_GATE_SANITIZE 0
```

bash:

```bash
echo 'export DOCUMENT_GATE_SANITIZE=0' >> ~/.bashrc
source ~/.bashrc
```

Pak restartujte Claude Code.


## Kam se ukládají soubory

| | Windows | WSL / Linux |
|---|---|---|
| Kopie (`sanitized_` a `converted_`) | `%USERPROFILE%\local_app\claude_document_gate\sanitized\` | `~/local_app/claude_document_gate/sanitized/` |
| Podpisový klíč | `%USERPROFILE%\local_app\claude_document_gate\verification.key` | `~/local_app/claude_document_gate/verification.key` |

Ke každé kopii `sanitized_<název>_<hash>.md` nebo `converted_<název>_<hash>.md` patří soubor `.meta.json`. Je v něm hash kopie, její podpis, verze sanitizace, příznak, jestli byla kopie sanitizovaná, a počet zamaskovaných hodnot podle typu. Hook kopii věří jen tehdy, když hash i podpis sedí.

`verification.key` je náhodný klíč, který vznikne při prvním použití. Podepisuje kopie a generuje značky. Nikomu ho nedávejte. Když ho smažete, vznikne nový a všechny dokumenty se při dalším odkazu na originál převedou znovu.

Nic se nemaže automaticky. Pokud jde o data zákazníků, staré kopie mažte sami.

Data můžete uložit jinam. Stačí nastavit proměnnou `DOCUMENT_GATE_HOME` na jinou složku v prostředí, kde Claude Code běží.

## Aktualizace

Přes git:

```bash
cd ~/tools/claude-document-gate
git pull
python3 install.py
```

Bez gitu: stáhněte nový ZIP a rozbalte ho přes stávající složku. Pokud jste upravovali `session_message.json`, nechte si svou verzi. Váš `config.json` v ZIPu není a zůstane, jak je. Pak znovu spusťte instalátor:

```powershell
cd C:\Tools\claude-document-gate
py -3 install.py
```

Pokud chcete aktualizovat i MarkItDown na nejnovější verzi, přidejte `--upgrade`:

```powershell
py -3 install.py --upgrade
```

Pokud jste používali starší verzi: soubory HTML, CSV, TXT a MD se už ve výchozím stavu nepřevádějí. Pro původní chování je přidejte do `convert_extensions`.

## Odinstalace

```powershell
py -3 install.py --uninstall
```

(ve WSL `python3 install.py --uninstall`)

Na macOS funguje `--uninstall` i bez `--allow-macos`.

Ze `settings.json` se odebere jen tenhle hook, ostatní zůstanou. Předchozí `settings.json` se uloží jako `settings.json.document-gate.bak`. Instalátor vypíše, kde leží složka `.venv` a sanitizované kopie. Nemaže je, takže pokud je už nepotřebujete, smažte je ručně. Pak restartujte Claude Code.

Pokud chcete složku projektu přesunout, nejdřív hook odinstalujte, složku přesuňte a v novém umístění znovu spusťte `install.py`.

## Řešení potíží

### Přepsaný prompt nedorazil do session

Hook váš prompt zablokuje a přepsaný pošle přes inbox session v Claude Code. Když to selže, hláška hooku uvede cestu k sanitizované kopii a na konci `Session notification failed:` s typem chyby. Původní prompt zůstane zablokovaný.

1. Napište `/status` a ověřte, že **Peer address** má hodnotu a není tam `unavailable`.
2. Pokračujte ručně. Zkopírujte cestu ke kopii z hlášky hooku do nového promptu:

```text
Shrň mi "C:\Users\me\local_app\claude_document_gate\sanitized\sanitized_report_9b1c47e0a2d3.md"
```

Hook tenhle prompt pustí, protože odkazuje jen na podepsanou kopii.

### Claude Code ukáže „Held peer message"

Celá hláška říká, že odesílatel nepotvrdil svůj režim oprávnění (sender did not attest its permission mode). Claude Code zprávu od hooku podržel a ptá se, jestli ji doručit. Jde o ověření odesílatele, dokument i převod jsou v pořádku.

Zvolte **Deliver this message to Claude**. Potvrzovat musíte každou zprávu zvlášť.

Nastavení `crossSessionInbound: "accept"` nedoporučujeme. Claude Code by pak přijímal zprávy od jakékoli jiné session na vašem počítači, nejen od tohoto hooku.

### Instalace selže na pip nebo síti

`settings.json` zůstane beze změny. Zkontrolujte připojení k internetu. Za firemní proxy nastavte před spuštěním instalátoru proměnnou `HTTPS_PROXY`. Pak instalátor spusťte znovu.

Pokud instalátor hlásí neúplné virtuální prostředí, smažte ve složce projektu složku `.venv` a spusťte ho znovu.

### Hook vůbec nereaguje

Restartujte Claude Code. Napište `/hooks` a ověřte, že je hook v seznamu. Zkontrolujte, že přípona souboru je v `convert_extensions` a že cesta je správně. Když soubor na dané cestě neexistuje, hook prompt pustí beze změny.

## Omezení a bezpečnost

### Neoficiální protokol pro doručení

Přepsaný prompt se do session posílá přes inbox socket Claude Code. Tenhle protokol není zdokumentovaný jako stabilní rozhraní. Implementace vychází z reverse engineeringu v [claude-code-socket-transport](https://github.com/PeterSR/claude-code-socket-transport) a z [dokumentace cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging). S jakoukoli aktualizací Claude Code se může změnit. Formát zprávy je proto v `session_message.json`, kde ho upravíte bez zásahu do kódu.

### Není to pevná bezpečnostní hranice

Když hook nedoběhne v časovém limitu (180 sekund), Claude Code může původní prompt pustit dál.

### Model může originál otevřít jinak

Hook kontroluje jen text vašeho promptu. Agent může originál otevřít jiným nástrojem, třeba Read nebo příkazem v shellu, pokud cestu k němu zjistí jinak. Když tomu chcete zabránit, přidejte pravidla `PreToolUse`, která přístup do těch složek zakážou.

### Názvy souborů jsou vidět

Sanitizovaná kopie nese původní název souboru, třeba `sanitized_Smlouva_Novak_<hash>.md`.

### Sanitizace je jen sada regulárních výrazů

Hodnoty v neobvyklém formátu může přehlédnout a naopak může zamaskovat neškodné číslo, které vypadá jako telefon. IBAN kontroluje podle délky pro danou zemi, bez kontrolního součtu. MarkItDown může vynechat obrázky, vložené objekty a některé tabulky.

### Přeskakované systémové zprávy jde napodobit

Zprávy od Claude Code hook pozná podle toho, jak začínají. Odpovídá to současnému formátu Claude Code a po aktualizaci to může přestat fungovat. Prompt, který začne stejně, třeba `[DOCUMENT_GATE:`, projde bez kontroly. Hook chrání před nechtěným únikem, vlastnímu uživateli v obejití nezabrání.

### Named pipe na Windows je méně otestovaná

Na Linuxu a ve WSL jde doručení přes Unix socket. Na Windows přes named pipe, která je zatím otestovaná méně.

## Pro pokročilé

### Soubory projektu

| Soubor | K čemu slouží |
|---|---|
| `hook.py` | Vstupní bod, který volá Claude Code. Přečte prompt, rozhodne o blokaci, pošle přepsaný prompt do session. |
| `document_gate.py` | Hledá cesty v promptu, převádí soubory, ukládá a ověřuje sanitizované kopie. |
| `sanitizer.py` | Regulární výrazy pro maskování. |
| `config.py` | Načte a zkontroluje konfiguraci ze souborů a proměnných prostředí. |
| `config.default.json` | Výchozí konfigurace, součást projektu. |
| `config.json` | Vaše konfigurace, vytvoří ji instalátor. Není součástí repozitáře. |
| `message_format.py` | Sestaví zprávu pro inbox session podle `session_message.json`. |
| `session_message.json` | Šablona zprávy pro inbox a text, který dostane model. |
| `session_transport.py` | Zapíše zprávu do Unix socketu (Linux, WSL) nebo do named pipe (Windows). |
| `install.py` | Instalace, aktualizace a odinstalace. |
| `tests/` | Testy, které spouští instalátor. |

### Volby instalátoru

| Volba | Co dělá |
|---|---|
| `--upgrade` | Aktualizuje MarkItDown a jeho závislosti. |
| `--skip-tests` | Přeskočí testy před zápisem hooku. |
| `--uninstall` | Odebere hook ze `settings.json`. |
| `--allow-macos` | Pokračuje v instalaci na macOS, který zatím není podporovaný. Pro `--uninstall` není potřeba. |

### Úprava session_message.json

`auth_frame` a `message_frame` jsou dva řádky, které jdou do inboxu. Můžou obsahovat `${token}`, `${session_id}`, `${msg_id}` a `${content}`. `body_template` je text pro model, z něj vznikne `${content}`. Může obsahovat `${prompt}` (váš přepsaný požadavek), `${files}` (seznam kopií), `${mode}` (`SANITIZED` nebo `CONVERTED`) a `${adj}` (`sanitized` nebo `converted (sanitization OFF)`).

Když Claude Code změní formát inboxu, měl by stačit zásah do tohoto souboru.

### Nová pravidla sanitizace

Do `PATTERNS` v `sanitizer.py` přidejte novou dvojici `(název, regex)`. Pak zvyšte `SANITIZER_VERSION` o jedna. Kopiím ze starší verze hook přestane věřit a každý dokument se při dalším odkazu převede znovu. Staré kopie `.md` zůstanou na disku, dokud je nesmažete.

### Spuštění testů

Windows:

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```

WSL / Linux:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Licence

MIT, viz [LICENSE](LICENSE). Copyright (c) 2026 Tomáš Nekolný.

Převod dokumentů dělá [Microsoft MarkItDown](https://github.com/microsoft/markitdown). Díky jeho autorům.
