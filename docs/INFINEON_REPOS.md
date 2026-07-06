# Открытая экосистема Infineon TRAVEO — что в ней есть и чего нет

Приборка Coolray/Binyue L (SX11-A5) построена на Infineon TRAVEO II (графика VIDEOSS /
cygfx). Infineon выкладывает SDK, инструменты и примеры **публично** на GitHub — именно
благодаря этому удалось восстановить формат RLAD. Ниже — полный разбор релевантных
репозиториев (результат глубокого анализа `github.com/Infineon`) и честный вывод: что
эта экосистема даёт, а что в ней принципиально отсутствует для нашей задачи.

## Ключевой вывод (сначала главное)

- ✅ **Формат пикселей (RLAD/RLA/RLC) — восстановим** по открытому SDK и энкодерам
  (мы это сделали, см. RLAD_FORMAT.md).
- ✅ **Формат одного ресурса (20-байт заголовок surface) — полностью задокументирован**
  в открытых примерах.
- ❌ **Таблицы-оглавления ресурсов НЕ существует ни у кого.** У Infineon ресурсы просто
  склеены встык в flash, а «индекс» — это хардкод-указатели (`const void* = 0x60...`) в
  коде приложения MCU, которые при компиляции превращаются в константы. То есть искать
  «таблицу» в NOR бессмысленно — её там нет by design.
- ❌ **Реализация декодера RLAD (`.cpp`) — закрыта** (только в прекомпилированной `.a`
  и в аппаратном GPU). Публичен лишь заголовок-интерфейс с полными параметрами — по
  нему декодер и реализован в этом проекте.
- ❌ **Формат контейнера Geely (`A5A5A5A5`) — НЕ Infineon.** Проверено: стандартных
  Infineon-контейнеров в нашем дампе нет (0 цепочек заголовков, 0 точных stride). Geely
  обернула данные по-своему; этой обёртки в открытых репозиториях Infineon нет и быть
  не может (она проприетарна у Geely).

## Релевантные репозитории

### SDK (главный источник форматов)
- **[Infineon/tviic2d-gfx-mw](https://github.com/Infineon/tviic2d-gfx-mw)** — Graphics
  Driver middleware для TRAVEO II Cluster (VIDEOSS/cygfx). Прекомпилированные `.a`
  + полные заголовки. Ключевые файлы:
  - `util_header/utgraphic/include/ut_class_rlad.h` — **интерфейс кодека RLAD/RLA/RL**:
    класс `RLAD` с методами `Encode`/`Decode`, `BitStream`, все константы (NUM_C=4,
    CNT_RLAD=8, MAX_CNT_RLA=32, MAX_CNT_RL=128), эндианность (RLAD/RLA — LE, RL — BE),
    per-package `cbpc[]` + delta-флаг, credit counter. Тело в закрытой `.a`.
  - `util_header/utgraphic/include/ut_rlc.h` — `utRldEncode` (RLD-битстрим).
  - `util_header/ResGen/include/ut_ResGen_convert.h` — форматы IRIS
    (`IRIS_FORMAT_RGBA=0x00`, `RGB_INDEX=0x01`, `RGBA_INDEX=0x03`, `RLD=0x04`),
    палитры `PAL_TYPE_*`, `read_color`/`write_color`/`util_convert`.
  - `util_header/ResGen/include/ut_ResGen_dump.h` — `storeDumpSurface` /
    `storeDumpSurfaceBin` (сериализация surface → заголовок ниже).
  - `util_header/hw/include/flash_resource.h` и `ext_flash_resource.h` — линкер-секции
    `.cygfx_res_section` / `.EXT_cygfx_res_section` (механизм «склейки встык»).
  - `util_header/utgraphic/include/sm_util.h` — `utSurfLoadBitmap`/`utSurfLoadBitmapEx`
    (рантайм-загрузчик: читает 20-байт заголовок, ставит атрибуты surface).
  - `util_header/utfreetype/include/ut_freetype.h` — текст через **FreeType** (векторные
    контуры), `utFtTextOut`, маппинг `FT_Get_Char_Index`.
  - `GFX_header/basic_graphics/include/cygfx_surfman.h` — `CYGFX_SM_COMP_*`
    (RLAD=0x0, RLAD_UNIFORM=0x1, RLA=0x2, RLC=0x3, NONE=0x4), атрибуты surface.

### Инструменты (оракулы)
- **[Infineon/mtb-t2g-example-graphics-sample-drawing](https://github.com/Infineon/mtb-t2g-example-graphics-sample-drawing)**
  — ⭐ содержит **ResourceGenerator.exe + Bin2Text.exe + readme.txt** в
  `tool/graphics/bin/windows/`. Генератор ресурсов (PNG → surface-массив/бинарь).
  Опции: `-c/-cRLA/-cRLAD/-cRLAD<rgba>` (сжатие), `-b` (бинарь), `-a` (append),
  `-p` (partitioning, line mode), `-fo<format>` (напр. `-foA8`), `-t/-d/-m` (палитры).
  Использован как оракул для реверса формата контейнера/A8.
- **[Infineon/mtb-example-psoc-edge-gfx-rlad](https://github.com/Infineon/mtb-example-psoc-edge-gfx-rlad)**
  — содержит **rlad-encoder.exe** в `utility/`. Оракул для реверса RLAD-пикселей.

### Примеры с реальными данными (эталоны формата)
- **[mtb-t2g-example-graphics-windowexample](https://github.com/Infineon/mtb-t2g-example-graphics-windowexample)**
  — ⭐ `res.c`/`res.h`: показывает, что «таблица ресурсов» = массив абсолютных
  указателей в HyperFlash (`const void* frame_0 = 0x60000000; ...`). Ключ к пониманию,
  что оглавления в NOR нет. Плюс `res/background.h` — эталон 20-байт заголовка.
- **[mtb-t2g-example-graphics-fir](https://github.com/Infineon/mtb-t2g-example-graphics-fir)**
  — `lenna.h` (реальная RGBA-картинка 400×400) и `courier_12.h` (битмап-«шрифт» = A1
  атлас с тем же 20-байт заголовком). Показывает оба пути шрифтов.
- Прочие: `-drawing-basic`, `-display-basic`, `-matrix`, `-jpeg-output`,
  `-empty-app`, `-emptytemplate`, `-fpd-link-hdmi-basic`, `-MIPI-CSI2_camera_capture`.

### Справочник форматов декодера
- **[Infineon/mtb-dsl-pse8xxgo](https://github.com/Infineon/mtb-dsl-pse8xxgo)** — enum'ы
  графики PSoC Edge: режимы `cy_en_gfx_rlad_comp_mode_t`, форматы `cy_en_gfx_rlad_fmt_t`
  (ARGB4444/ARGB1555/RGB565/ARGB8888/RGB888/RGB666/RGB444/GRAY8/GRAY6/GRAY4).

## 20-байтный заголовок ресурса Infineon (byte-for-byte)

Подтверждён идентичным в нескольких эталонных `.h`:
```
+0  u32  nSize          полный размер записи вкл. заголовок (LE)
+4  u16  nWidth         пиксели
+6  u16  nHeight        пиксели
+8  u16  strideInByte   байт на строку
+10 u8   totalBits      бит на пиксель (0x20=32, 0x08=A8, 0x01=A1)
+11 u8   flags          формат/сжатие
+12 u32  ColorComponentBits   напр. 0x08080808 = R8G8B8A8
+16 u32  ColorComponentShift  напр. 0x00081018 (A на младших битах)
+20 ...  данные (или палитра+индексы, или сжатый поток)
```
Правило склейки: следующий ресурс начинается на `off + nSize`. Индексация в рантайме —
абсолютными указателями в область `0x60000000` (SMIF/HyperFlash XIP).

> В нашем дампе Coolray этот заголовок НЕ встречается цепочкой (проверено). Geely
> использует собственную обёртку `A5A5A5A5`, которой в открытых репо Infineon нет.

## Даташиты и Kit (свободно скачиваются с infineon.com)

- **CYT3DL datasheet** (doc 002-27763) — [documentation.infineon.com/traveo](https://documentation.infineon.com/traveo/docs/bxw1678767622519).
  Карта памяти, security, boot.
- **SEMPER Flash S25HL/HS512T datasheet** (doc 002-12345) — полный, 180 стр., есть
  на зеркалах DigiKey/Mouser. Разметка секторов, SSR, AutoBoot.
- **KIT_T2G_C-2D-4M_LITE / -6M_LITE** — оценочные платы кластера на CYT3DL. User Guide
  (doc 002-39200) свободно. Показывает: SEMPER NOR на SMIF-0, HyperRAM на SMIF-1.
- **SMIF training** PDF — [infineon SMIF training](https://www.infineon.com/assets/row/public/documents/10/56/infineon-traveo-ii-serial-memory-interface-smif-training-en.pdf).
- **За логином (бесплатная регистрация):** AN220242 (flash access), **AN228680**
  (secure system config — важен: подтвердить, проверяет ли secure boot внешний NOR),
  TRAVEO II Architecture/Registers TRM (глава VIDEOSS/графика).
- Полезные SDK-примеры: `Infineon/mtb-t2g-example-smif-qspi-flash-read-write` (init
  SMIF/XIP, линкер-файлы), `Infineon/mtb-t2g-example-secure-boot`.

## Расшифровка нашего железа (по даташитам)

**MCU `CYT3DLABHBQ1AES`** (декод части по §27.1 datasheet):
- `3`=TRAVEO T2G, `D`=Core M7 Single, `L`=**4160 КБ code-flash / 128 КБ work / 384 КБ SRAM**,
  `A`=216-TEQFP, `B`=**Security ON (HSM), RSA-3K**, S-grade (−40…+105°C).
- Внутр. flash @ `0x10000000`; 64 КБ Secure Boot ROM @ `0x01000000`; **2048 КБ VRAM**.
- Secure boot управляется структурой **TOC2** во flash; eSHE/HSM включаются firmware.

**NOR `S25HL512TFB01`** (декод по §11.2 datasheet):
- `HL`=**3.0 В** (2.7–3.6В), 512 Мбит=**64 МБ**, SEMPER 45нм, Grade 2 (−40…+105°C).
- Разметка секторов конфигурируема: uniform 256×256КБ, либо **hybrid** — 32×4КБ
  параметр-сектора в НАЧАЛЕ или в КОНЦЕ (мелкие 4КБ обычно = boot-header/метаданные).
- Спец-зоны: **SSR** (1024-байт OTP, читается спец-командой — в обычном дампе НЕ виден),
  SFDP, **AutoBoot** (автострим с запрограммированного адреса при старте).

## Адресная модель (ключевое для интерпретации дампа)

- Внешний NOR мапится в CPU по **XIP-окну `0x60000000`** (SMIF0/CS0). Второй чип — во
  второе окно. Значит указатель в прошивке = `0x60000000 + <offset в NOR>`.
- **Правило для таблиц:** любое 32-битное значение проверять и как flash-offset
  (0-based), и как абсолютный XIP-адрес (`value − 0x60000000`).

## Secure boot и внешний NOR (важный вывод)

Цепочка аутентификации TRAVEO (BootROM → Flash Boot → CM0+ app) проверяет **внутреннюю
flash MCU**. По имеющимся данным (datasheet + AN228680 портал) **нет свидетельств, что
BootROM аутентифицирует содержимое внешнего SMIF NOR** — внешние графические ресурсы
обычно проверяются (если вообще) самим приложением, не mask-ROM. **Практический смысл:**
правка внешнего NOR, скорее всего, аппаратно НЕ отвергается secure-boot'ом. Требует
финального подтверждения по AN228680 (за логином).

## Защита доступа к MCU: NAR/SAR + lifecycle (ПОДТВЕРЖДЕНО на нашем чипе)

На форуме Infineon есть тема ровно про наш MCU **CYT3DLABHBQ1AES**, где не удаётся
прошить **product**-плату (тот же код шьётся на eval-плате `CYT3DLABHB*B*ES`, но не на
серийной). Модератор Infineon объясняет причину — **Access Restrictions**:
- **NAR / SAR** (Normal / Secure Access Restrictions) — ограничивают доступ по отладке;
  debug access port CM0+ может быть **заблокирован (временно или НАВСЕГДА)**.
- Проверяется по **lifecycle stage** (NORMAL vs **SECURE**): регистры
  `CPUSS_AP_CTL` @ `0x1700_1A00` и `CPUSS_PROTECTION`.

Тема (EN, + зеркала CN/JP/TW):
<https://community.infineon.com/t5/TRAVEO-T2G/Flashing-failed-for-CYT3DLABHBQ1AES-product-development-board/td-p/1010153>

**Что это значит для нашей приборки (рассуждение — чип vs память):**
- Приборка Geely — это **серийное (product) устройство в SECURE lifecycle с закрытым
  debug-портом**. Значит снять дамп **внутренней flash MCU** (где таблица ресурсов)
  через SWD/JTAG **практически невозможно** — упрёшься в NAR/SAR ровно как в этой теме.
  Раньше это была наша осторожная гипотеза («HSM заблокирует»), теперь — **подтверждено
  реальным кейсом Infineon на том же чипе**.
- НО ограничения NAR/SAR касаются доступа **к самому MCU по отладке**. Они **НЕ мешают
  читать/писать ВНЕШНИЙ NOR** программатором — это отдельные микросхемы
  (S25HL512TFB01), которые мы уже успешно считали (дампы U17/U18 есть).

**Итоговая картина памяти приборки:**
| Память | Где | Доступ |
|--------|-----|--------|
| Внутр. flash MCU (4160КБ) — код + **таблица ресурсов** | внутри CYT3DL | ❌ закрыта (SECURE + NAR/SAR, подтверждено) |
| Внешний NOR 2×64МБ — графика/RLAD-ассеты | S25HL512TFB01 | ✅ читается/пишется программатором (дампы есть) |

Отсюда стратегия: MCU не трогаем (закрыт), работаем с NOR, а недостающую привязку
«что где лежит» добываем **diff'ом двух языков**, а не дампом MCU.

---

## Работа с NOR-чипом S25HL512T: чтение и запись (практика)

Раз MCU закрыт, вся работа — с внешними NOR. Здесь всё, что нужно, чтобы снять дамп
и залить обратно.

### Идентификация чипа
- **Part number `S25HL512TFB01` — НЕ полный каталожный номер**, а сокращение/маркировка.
  Расшифровка полей: `HL`=3.0В (2.7–3.6В), `512T`=512Мбит (64МБ) 45нм, `F`(A)=скорость,
  `B`=**корпус 24-ball BGA 6×8мм**, `01`=модель (BGA/WSON/SOIC). Полный аналог для
  заказа: `S25HL512TFABHI010`. Именно поэтому его не найти в каталоге.
- **JEDEC RDID (команда 0x9F) = `34 2A 1A` (+ ext `0F 03 90`)** — по нему чип
  опознаётся однозначно. `34`=Infineon/Cypress, `2A`=HL(3.0В), `1A`=512Мбит.
- Даташит (публичный, бесплатный): doc **002-23880** (зеркала MikroE/SparkFun/Mouser).
  Полный (регистры/NVCR/SFDP) — 002-25784/002-27182, за Semper Access Program.

### ⚠️ 4-байтовая адресация — критично
Чип 64МБ (>16МБ) → чтение/запись за пределами 16МБ требует **4-байтовых опкодов**
(READ 0x13, PP 0x12, ERASE 0xDC) или входа в 4-byte режим (`EN4B`, 0xB7). Инструменты,
не умеющие этого, **молча прочитают только первые 16 из 64 МБ** (битый неполный дамп).

### Чем читать/писать (по убыванию надёжности)
| Инструмент | Поддержка S25HL512T | 4BA | Стоимость |
|-----------|---------------------|-----|-----------|
| **Linux MTD `spi-nor`** | ✅ явно (`s25hl512t` в `spansion.c` ядра) | авто | бесплатно/open |
| **SEGGER Flasher** | ✅ явно (страница поддержки) | да | коммерч. |
| **Dediprog SF100/SF600 (Windows GUI)** | ✅ явно | да | ~$150–800 |
| Xeltek SuperPro | ❓ проверять | — | коммерч. |
| **CH341A + AsProgrammer/NeoProgrammer** | ❌ нет в базе, 3-байт адрес | ❌ обрежет на 16МБ | ~$5–15 |
| **XGecu T48/T56/T76** | ❌ нет в списке (v13.16) | — | ~$50–90 |
| **flashrom / libflashrom** | ❌ нет записи (id не в базе) | generic | бесплатно |
| Elnec BeeProg | ❌ нет | — | коммерч. |

**НЕ использовать CH341A/EZP** — обрежут 64МБ до 16МБ. Наши дампы полные (64МБ) —
значит сняты правильным инструментом.

Linux MTD подтверждён (ядро `drivers/mtd/spi-nor/spansion.c`):
```c
{ .id = SNOR_ID(0x34, 0x2a, 0x1a, 0x0f, 0x03, 0x90), .name = "s25hl512t", ... }
```
Геометрия и 4BA определяются автоматически по SFDP.

### Открытые решения/SDK Infineon для QSPI/SEMPER (через SFDP, без явного имени чипа)
- [Infineon/serial-flash](https://github.com/Infineon/serial-flash) — QSPI-библиотека (Apache-2.0).
- [Infineon/serial-memory](https://github.com/Infineon/serial-memory) — внешняя память (Apache-2.0).
- [Infineon/mtb-pdl-cat1](https://github.com/Infineon/mtb-pdl-cat1) — SMIF/QSPI PDL-драйвер.
- Примеры: `mtb-example-psoc6-qspi-readwrite-sfdp`, `mtb-t2g-example-smif-qspi-flash-read-write`.
- **SEMPER LLD** (Low Level Driver, C: read/program/erase/register/4BA) — за аккаунтом
  Infineon (Memory Solutions Hub). Не на GitHub.
- Eval-board для самого чипа: `EVAL-S25HL512T`.

### Физика (для чип-оффа)
- Корпус BGA-24 6×8мм → нужен адаптер BGA24→DIP8 (6×8мм) или пайка in-circuit к линиям
  QSPI (CS#, CK, DQ0–DQ3) с удержанием MCU в reset. Питание **3.0В** (не 3.3 вслепую).
- Reset: CS#-signaling, вывод RESET# или DQ3/RESET#.

> Итог: снять/залить эти NOR — решаемо готовыми инструментами (Linux spi-nor / SEGGER /
> Dediprog). Наши дампы уже сняты корректно. Барьер проекта не в железе NOR, а в
> отсутствии таблицы ресурсов (в закрытом MCU) — решается diff'ом двух языков.

---

## Инструменты Infineon для РЕДАКТИРОВАНИЯ содержимого bin (не чипа, а ресурсов)

Отдельно от чтения/записи самого чипа — вопрос: чем Infineon предлагает
читать/декодировать/править/пересобирать САМИ РЕСУРСЫ (картинки/глифы) внутри образа.

### Главный вывод: публичные инструменты — ТОЛЬКО кодирование (image → bin). Декодера НЕТ.
Проверено по всем каналам — вся публичная экосистема односторонняя, декодирование
выполняет **аппаратный GPU** в рантайме, а не софт:
| Инструмент | Направление | Может bin→картинка? |
|-----------|-------------|---------------------|
| `ResourceGenerator.exe` | PNG → C-массив / bin | ❌ нет обратного режима |
| `Bin2Text.exe` | bin → C-текст (char array) | ❌ только в текст-массив, не в картинку |
| `rlad-encoder.exe` | PNG → .h | ❌ декод делает GPU |
| `ut_ResGen_png.h` | только `png_Read` (PNG→буфер) | ❌ нет `png_Write` |
| TRAVEO T2G Virtual Display Tool | стрим экрана живой платы по USB | ❌ не читает файл-дамп |

**Готового «bin → PNG» у Infineon нет by design.** Именно поэтому в этом проекте
пришлось реконструировать RLAD методом oracle — переиспользовать было нечего. Наш
`geely_cluster/rlad_decoder.py` остаётся единственным рабочим софтовым декодером.

Смежные пути тоже НЕ дают декод контента:
- **Kanzi / Candera CGI Studio / Qt** — авторинг-фронты, экспортируют свои forward-only
  форматы, формат Infineon RLAD/surface НЕ декодируют. Kanzi — это CMA-платформы на
  Linux (у нашей A5 его нет). KZB-Explorer (неофиц.) — только меши, без repack.
- **SEMPER LLD** — только чип (read/program/erase байтов), контент не трактует.
- **SMIF-примеры** (`mtb-t2g-example-smif-*`) — только механика flash, не индексируют
  ресурсы.

### 🎯 Углубление: `03_build` и myICP — ЕДИНСТВЕННАЯ непройденная зацепка на фронте инструментов

`readme.txt` ResourceGenerator (v3.00) прямо говорит (verbatim):
> **"The Resource Generator source code is available in 03_build folder."**

Но на GitHub папка **`03_build` ВЫРЕЗАНА** — в публичном репозитории только
скомпилированные `ResourceGenerator.exe` + `Bin2Text.exe` в `tool/graphics/bin/windows/`.
Доказательство, что это подмножество большего пакета: `resource_generator_examples.bat`
ссылается на `..\..\..\..\04_sample\...` — значит полная поставка имеет структуру
`01_.. / 02_.. / 03_build / 04_sample`, и из GitHub-зеркала убрали `03_build` и
`04_sample`.

**Что, вероятно, лежит в `03_build` (и почему это ценно):**
- **C-исходник `storeDumpSurfaceBin`** — писатель контейнера surface (20-байт заголовок
  + сжатый payload). Его сигнатура публична (`ut_ResGen_dump.h`), но тело — здесь.
  Инвертировав его, получаем ТОЧНЫЙ формат контейнера и надёжный декодер.
- **Исходник RLAD/RLA/RLC кодека** — проверенный энкодер И, вероятно, ссылочный
  декодер (вместо нашего oracle-реконструированного).
- Возможно, полный **энкодер для обратной сборки** (пересборка правленых ресурсов).

**Где взять `03_build` (полный пакет "Graphics Driver for TRAVEO T2G cluster"):**
- Лежит на **myInfineon Collaboration Platform (myICP)** — GATED, но **регистрация
  бесплатна**. По README примеров: *"...available on the myInfineon Collaboration
  Platform (MyICP). ...create a myInfineon account... Then contact traveo@infineon.com
  and request access to TRAVEO T2G myICP."*
- Шаги: (1) создать бесплатный аккаунт myInfineon; (2) написать на **traveo@infineon.com**
  с запросом доступа к TRAVEO T2G myICP; (3) скачать полный пакет графического драйвера;
  (4) взять `03_build` → исходники ResourceGenerator + RLAD-кодека.

**Оговорки честно:**
- Доступ дают на усмотрение Infineon (обычно инженерам/партнёрам; не гарантирован).
- Материалы под лицензией Infineon (EULA) — их **нельзя выкладывать** в этот
  open-source репозиторий; можно лишь использовать для реализации своего декодера.
- Это **НЕ решает** главный барьер (таблица ресурсов в закрытом MCU) — даёт лишь
  точный формат/декодер. Локализация всё равно упирается в diff двух языков.

**Статус в проекте:** зацепка зафиксирована как непройденная. Требует у кого-то из
сообщества myInfineon-аккаунта и запроса; результат (исходники) применим для проверки
нашего `rlad_decoder.py` и построения точного энкодера обратной сборки.
