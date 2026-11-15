# «Монтажная» — план и архитектура

Локальный дашборд монтажа Reels: http://127.0.0.1:8790, запуск `D:\Монтаж\Монтажка.bat`. Без платных API.

## Как подключаю то, что уже есть (ничего там не меняю)

| Что | Как используется |
|---|---|
| **Captions Studio** `D:\Captions my` | **Распознавание:** запускаю его `backend.transcribe_worker` отдельным процессом в его же `.venv` (faster-whisper large-v3-turbo, CUDA → CPU). Модель второй раз не качается. **Субтитры:** `frontend\engine.js` раздаю в браузер дашборда как есть (только чтение) → тот же Canvas-превью и тот же `.ass`. **Вшивание:** импортирую `backend.render` (фильтры, эмодзи PNG, пресет экспорта Instagram/TikTok/Facebook). Пресеты, шрифты, эмодзи, словарь и паразиты из `settings.json` читаю; новые пресеты пишу в `presets\user\` в его формате. |
| **Моушн-студия** `D:\Моушн-графика` | Если не запущена, поднимаю её `npm start` (порт 3000) и работаю через её HTTP API: шаблоны, бренд, `/api/render` (прозрачный фон / хромакей, MOV ProRes 4444 / WebM), `/api/history`, генерация через Claude CLI по подписке, `npm run reel`. Готовые клипы беру из `output\`. |
| **reels-montage-kit** | Беру логику и правила: вырезка пауз и дублей (`prep.py`), правила хука, punch-in и графики на словах (`references\beat-planning.md`, `move-bank.md`), звук и ducking (`finish.py`, `sound-design.md`), разбор стиля (`analyze_reference.py`, `style-profiles.md`). Всё, что шло в OpenAI, заменяю: речь — whisper из Captions Studio, склейки — PySceneDetect, громкость — ffmpeg `ebur128`, внешний вид — кадры каждые 1–2 с, которые смотрю я. HyperFrames-движок кита (уже установлен) — для новых сцен. |

**Уточнение Руслана:** монтажные инструменты Captions Studio (хук и т. п.) не использовать. Из неё берём только
распознавание и движок самих субтитров. Хук, графика и подача делаются по примерам роликов, которые пришлёт Руслан.

## Структура

```
D:\Монтаж\
  Монтажка.bat            запуск (поднимает .venv при первом старте, открывает браузер)
  studio\
    backend\  app.py (FastAPI :8790) · projects.py · sources.py · jobs.py
              transcribe.py   → worker Captions Studio
              find_cuts.py    паузы > 0,35 с, паразиты, дубли, фальстарты
              analyze_style.py PySceneDetect + whisper + ebur128 + кадры → styles\<имя>.json
              compose.py      таймлайн → граф ffmpeg (кроп по лицу opencv, punch-in, моушн-оверлеи, музыка+ducking)
              render.py       очередь: превью 720p → финал 1080×1920 (пресет Captions Studio)
              motion.py       клиент API моушн-студии + простые ffmpeg/HyperFrames-анимации
              rules.py        styles\my_rules.md
    frontend\ index.html, app.js, styles.css (тёмная тема как у Captions Studio)
    .venv\    Python 3.12 через uv из Captions Studio
  styles\     <имя>.json, my_rules.md
  work\       всё временное, по проектам
  output\     <дата>_<название>.mp4
```

Исходники только читаются. Каждая новая папка исходников: дашборд спрашивает подтверждение, список разрешённых папок хранится в проекте.

## Этапы (после каждого — показ и твоё «ок»)

1. План и архитектура ← сейчас
2. Каркас дашборда + Исходники (превью, длительность, разрешение, fps, выбор клипов)
3. Транскрипция и Чистка (таблица правок, ▶, ✓/✗, «Принять всё», склейки 40–80 мс + кроссфейд)
4. Референсы и стили (карточка стиля, ближайший пресет субтитров)
5. Монтаж с субтитрами (хук, кроп по лицу, punch-in 1,1–1,2×, таймлайн)
6. Моушн-слой (библиотека, рендер шаблонов с твоими текстами, мои предложения графики на словах)
7. Рендер и Мои правила, затем тест на твоём видео

## Зависимости

Есть: Python 3.12 (у Captions Studio), ffmpeg 9, Node 24, моушн-студия с node_modules, GTX 1650 Ti (4 ГБ).
Нужно поставить в `studio\.venv` (≈150 МБ, только с твоего «да»): fastapi, uvicorn, python-multipart, numpy, pillow,
opencv-python-headless, scenedetect, fonttools.
