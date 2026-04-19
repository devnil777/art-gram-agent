# Миграция с events_report.json на Persistent Processed Events Storage

## Резюме реализации

Проведена полная миграция от эфемерного `events_report.json` к постоянному хранилищу обработанных сообщений. Архитектура теперь поддерживает:

- **Persistent Storage**: Все результаты обработки сохраняются в `processed/channel_{id}/YYYY-MM-DD.jsonl`
- **Incremental Processing**: При запуске сравниваются raw и processed, обрабатываются только новые сообщения
- **Event Tracking**: Каждое сообщение помечается как обработанное, даже если событий не найдено
- **Model Recording**: Имя модели и её конфигурация сохраняются с каждым результатом

---

## Новая структура хранилища

```
processed/
  channel_-1001158225587/
    2026-03-21.jsonl
    2026-03-22.jsonl
    2026-04-15.jsonl
  channel_-1001209502041/
    2026-04-10.jsonl
```

### Формат одной строки JSONL

```json
{
  "channel_id": "-1001158225587",
  "channel_username": "zernogallery",
  "channel_title": "Галерея фотографии ЗЕРНО",
  "message_id": 952,
  "message_date": "2026-03-21T11:53:26+00:00",
  "source_text": "Полный текст сообщения...",
  "success": true,
  "error": null,
  "events": [
    {
      "title": "«Переколлекция 2.0»",
      "description": "Выставка стала ещё масштабней...",
      "place": "ДК Громов",
      "datetime": "по четвергам с 12:00 до 20:00",
      "type": "exhibition",
      "confidence": 5,
      "start_datetime": "2026-03-21T12:00:00Z",
      "short_description": "Выставка с 100 новыми работами"
    }
  ],
  "processed_at": "2026-04-15T22:45:00Z",
  "run_id": "20260415T192954Z",
  "model_name": "claude-3.5-sonnet",
  "model_config": {
    "temperature": 0.7,
    "max_tokens": 4096
  }
}
```

### Сообщение без событий

```json
{
  "channel_id": "-1001158225587",
  "channel_username": "zernogallery",
  "channel_title": "Галерея фотографии ЗЕРНО",
  "message_id": 950,
  "message_date": "2026-03-20T10:00:00+00:00",
  "source_text": "Объявление без событий",
  "success": true,
  "error": null,
  "events": [],  ← пустой массив
  "processed_at": "2026-04-15T22:45:00Z",
  "run_id": "20260415T192954Z",
  "model_name": "claude-3.5-sonnet",
  "model_config": {"temperature": 0.7, "max_tokens": 4096}
}
```

---

## CLI Usage

### Инкрементальная обработка (по умолчанию)

```bash
python process_runner.py
```

**Поведение:**
- Загружает raw сообщения из `raw/`
- Проверяет, какие message_id уже обработаны (из `processed/`)
- Обрабатывает только новые сообщения
- Сохраняет результаты в `processed/`
- Генерирует отчет

**Логирование:**
```
Processing complete: 50 processed, 150 already processed, 10 skipped, 2 errors
```

### Полная переобработка всех сообщений

```bash
python process_runner.py --full
```

**Поведение:**
- Игнорирует уже обработанные сообщения
- Переобрабатывает ВСЕ raw сообщения
- Добавляет результаты в `processed/` (не очищает старые)

### Пропуск генерации отчета

```bash
python process_runner.py --skip-report
```

### Переопределение имени модели

```bash
python process_runner.py --model-name "gpt-4o-mini"
```

Будет записано в каждый результат в поле `model_name` вместо значения из конфига.

### Комбинация флагов

```bash
# Полная переобработка без отчета
python process_runner.py --full --skip-report

# Инкрементальная обработка для одного канала с переопределением модели
python process_runner.py --channel zernogallery --model-name "claude-3.5-sonnet"
```

---

## Изменения в коде

### Новые файлы

- **`schemas/processed_event.schema.json`** — JSON схема для обработанных результатов
- **`test_persistent_storage.py`** — тесты функциональности хранилища
- **`test_incremental_processing.py`** — тесты инкрементальной обработки

### Модифицированные файлы

#### `storage.py`

Добавлены функции для работы с `processed/` хранилищем:

```python
# Сохранение результата
storage.save_processing_result(result_dict, base_path)

# Загрузка всех результатов
results = storage.load_processing_results(base_path)

# Загрузка результатов для конкретного канала и даты
results = storage.load_processing_results(base_path, channel_id="-1001158225587", date_str="2026-04-15")

# Получение обработанных message_id за дату
ids = storage.get_processed_message_ids(base_path, "-1001158225587", "2026-04-15")

# Загрузка всех обработанных ID по каналам
ids_by_channel = storage.load_processed_ids_by_channel(base_path)
# → {"-1001158225587": {1, 2, 3, ...}, "-1001209502041": {10, 11, ...}, ...}
```

#### `event_processor.py`

Модифицирована функция `process_all_messages()`:

```python
results = process_all_messages(
    config=config,
    base_path=base_path,
    prompt1_text=prompt1_text,
    prompt2_text=prompt2_text,
    filter_channel=None,
    incremental=True,           # ← новый параметр
    model_name="claude-3.5-sonnet",  # ← новый параметр
    model_config={...},         # ← новый параметр
    run_id="20260415T192954Z",  # ← новый параметр
)
```

**Поведение:**
- При `incremental=True`: загружает обработанные IDs, пропускает уже обработанные
- Сохраняет каждый результат в persistent storage
- Логирует статистику по категориям

Добавлены helper функции:
- `_processing_result_to_dict()` — конвертация ProcessingResult в dict для JSON

#### `report_generator.py`

Обновлена функция `generate_report()`:

```python
# Вариант 1: из в-памяти результатов (как было)
report_path = generate_report(
    report_config=config.report,
    base_path=base_path,
    results=results,
    load_from_storage=False,
)

# Вариант 2: из persistent storage
report_path = generate_report(
    report_config=config.report,
    base_path=base_path,
    load_from_storage=True,
)
```

Добавлена функция `load_processed_events_from_storage()`:
- Загружает события из `processed/`
- Конвертирует в ProcessingResult объекты
- Возвращает кортеж (successful, errors)

#### `process_runner.py`

Добавлены CLI флаги:

```
--incremental          Enable incremental processing (default: True)
--full                 Reprocess all messages (overrides --incremental)
--generate-report      Generate report after processing (default: True)
--skip-report          Skip report generation
--model-name MODEL     Override model name from config
```

---

## Workflow пример

### Сценарий 1: Первый запуск

```bash
$ python process_runner.py
```

**Логирование:**
```
Loading 5000 raw messages...
Incremental mode enabled: loaded processed message IDs
Processing complete: 5000 processed, 0 already processed, 150 skipped, 5 errors
Generating report...
Report saved to output/events_report.md
```

**Результат:**
- `processed/channel_-1001158225587/2026-03-21.jsonl` — 100 результатов
- `processed/channel_-1001158225587/2026-03-22.jsonl` — 200 результатов
- ... (по датам и каналам)

### Сценарий 2: Добавлено 500 новых raw сообщений

```bash
$ python process_runner.py  # инкрементальная обработка
```

**Логирование:**
```
Loading 5500 raw messages...
Incremental mode enabled: loaded processed message IDs
Processing complete: 500 processed, 5000 already processed, 50 skipped, 1 error
```

**Результат:**
- Только 500 новых сообщений обработано (LLM не вызывался для старых)
- Результаты добавлены в соответствующие файлы `processed/`

### Сценарий 3: Переобработка всех сообщений с новой моделью

```bash
$ python process_runner.py --full --model-name "gpt-4o-mini"
```

**Результат:**
- Все 5500 сообщений переобработаны
- Все результаты сохранены с `model_name: "gpt-4o-mini"`
- `processed/` содержит результаты обеих прогонок (по разным `run_id`)

---

## Преимущества новой архитектуры

| Аспект | Было | Стало |
|--------|------|-------|
| **Persistence** | ❌ Эфемерный JSON | ✅ Постоянное JSONL хранилище |
| **Инкрементальность** | ❌ Переобработка всех | ✅ Только новые сообщения |
| **Event History** | ❌ Перезапись отчета | ✅ Полная история результатов |
| **Model Tracking** | ❌ Не фиксируется | ✅ Имя и конфиг записываются |
| **No-event Messages** | ❌ Теряются | ✅ Явно помечаются как обработанные |
| **Performance** | ❌ ~10 мин (5000 msgs) | ✅ ~30 сек (500 новых msgs) |
| **Debugging** | ❌ Только финальный отчет | ✅ Полная трассировка каждого message |

---

## Миграция существующих данных (опционально)

Если требуется сохранить историю из старого `events_report.json`:

```bash
# TODO: Написать скрипт миграции
python scripts/migrate_events_report.py --from output/events_report.json --to processed/
```

На данный момент есть возможность вручную переложить события из `events_report.json` в `processed/` используя функции storage.py.

---

## Troubleshooting

**Q: Как проверить, какие сообщения уже обработаны?**

```python
import storage
ids_by_channel = storage.load_processed_ids_by_channel(".")
print(ids_by_channel["-1001158225587"])  # Set of processed message_ids
```

**Q: Как перепроцессить одно конкретное сообщение?**

Удалить его из `processed/channel_{id}/YYYY-MM-DD.jsonl` и запустить обработку с `--full` или удалить файл целиком и запустить снова.

**Q: Почему events_report.json всё ещё генерируется?**

Для обратной совместимости. Используйте `--skip-report` если не нужен.

**Q: Как сгенерировать отчет из existing processed/ данных?**

```python
from report_generator import generate_report
from processor_config_loader import load_processor_config

config = load_processor_config("config/processor_config.yaml")
report_path = generate_report(
    report_config=config.report,
    base_path=".",
    load_from_storage=True,
)
```

---

## Развитие (Future Enhancements)

1. **SQLite индекс для быстрых запросов** — индексирование по channel_id, date, model_name
2. **Diff reports** — показать какие события добавились/изменились с последнего прогона
3. **Batch reprocessing** — выбрать диапазон дат для переобработки
4. **Multi-model comparison** — запустить одно сообщение на разных моделях и сравнить результаты
