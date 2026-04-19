# Отслеживание отправленных сообщений - Документация изменений

## Краткое резюме

Реализована функциональность для **отслеживания отправленных событий** в целевые Telegram-каналы. Система теперь может:

1. **Фиксировать** какие события были отправлены в какой канал
2. **Управлять** глубиной поиска (количество дней для анализа)
3. **Избегать** повторной отправки уже опубликованных событий

## Файлы, которые были изменены

### 1. `storage.py` - Новые функции для хранилища

Добавлены **4 новые функции** для работы с отправленными событиями:

#### `sent_dir(base_path: str) -> str`
- Возвращает путь к директории `sent/` для хранения информации об отправках

#### `sent_file_path(base_path: str, target_identifier: str) -> str`
- Возвращает путь к файлу отправок для конкретного целевого канала
- Пример: `sent/@my_channel.jsonl` или `sent/my_channel_id.jsonl`

#### `mark_events_as_sent(base_path, target_identifier, event_ids) -> None`
```python
# Записать что события были отправлены в канал
mark_events_as_sent(
    base_path=".",
    target_identifier="@news_channel",
    event_ids=[
        {"channel_id": "channel_123", "message_id": 456},
        {"channel_id": "channel_123", "message_id": 457},
    ]
)
```

**Формат сохраняемого файла** (`sent/channel_identifier.jsonl`):
```json
{"target": "@news_channel", "channel_id": "channel_123", "message_id": 456, "sent_at": "2026-04-19T15:30:00+00:00"}
{"target": "@news_channel", "channel_id": "channel_123", "message_id": 457, "sent_at": "2026-04-19T15:30:00+00:00"}
```

#### `load_sent_events(base_path, target_identifier=None) -> Dict[str, set]`
```python
# Загрузить все отправки по всем каналам
sent_map = load_sent_events(".")
# Результат: {"@channel1": {"channel_123:456", "channel_123:457"}, ...}

# Загрузить отправки для конкретного канала
sent_map = load_sent_events(".", target_identifier="@news_channel")
# Результат: {"@news_channel": {"channel_123:456", "channel_123:457"}}

# Проверить было ли событие отправлено
is_sent = "channel_123:456" in sent_map["@news_channel"]
```

---

### 2. `report_generator.py` - Фильтрация отправленных событий

#### Обновлена функция `generate_report_text()`

**Новые параметры:**
- `target_identifier: Optional[str] = None` - Целевой канал для отправки
- `skip_already_sent: bool = False` - Пропустить уже отправленные события
- `days: Optional[int] = None` - Переопределить дни из конфига

**Логика работы:**
```python
pages = generate_report_text(
    report_config=config,
    base_path=".",
    results=None,
    load_from_storage=True,
    page_size_bytes=4096,
    target_identifier="@news_channel",  # <- Целевой канал
    skip_already_sent=True,              # <- Исключить отправленные
    days=7,                              # <- Последние 7 дней
)
```

Если `skip_already_sent=True`:
1. Загружает информацию об отправленных в целевой канал
2. Исключает события из результата, если они уже были отправлены
3. Возвращает только новые события

---

### 3. `news_sender.py` - Отправка и фиксирование

#### Добавлена функция `_extract_sent_events()`
Вспомогательная функция для извлечения списка событий, которые будут отправлены.

#### Обновлена функция `send_news_summary()`

**Новый параметр:**
- `skip_already_sent: bool = False` - Пропустить уже отправленные события

**Новая логика:**
1. Вызывает `generate_report_text()` с параметром `skip_already_sent`
2. После успешной отправки записывает события в хранилище
3. Логирует количество отправленных событий

**Пример:**
```python
await send_news_summary(
    app_config_path="config/app.yaml",
    processor_config_path="config/processor_config.yaml",
    base_path=".",
    target="@my_channel",
    report_days=7,
    skip_already_sent=True,  # <- Новый параметр
)
```

#### Добавлены параметры командной строки

```bash
# Основное использование
python news_sender.py --target @my_channel --report-days 7 --skip-sent

# Где:
#  --skip-sent      Пропустить события уже отправленные этому каналу
#  --report-days N  Переопределить количество дней поиска
```

---

## Примеры использования

### Пример 1: Отправить только новые события

```bash
# Каждый день отправляем только события, которые еще не были публикованы
python news_sender.py --target @news --report-days 7 --skip-sent
```

### Пример 2: Переотправить все события за неделю

```bash
# Отправить ВСЕ события, даже если они уже были отправлены
python news_sender.py --target @news --report-days 7
```

### Пример 3: Разные каналы получают разные наборы

```bash
# Основной канал - только новое за 3 дня
python news_sender.py --target @main_channel --report-days 3 --skip-sent

# Архив - все за месяц
python news_sender.py --target @archive_channel --report-days 30
```

### Пример 4: Проверка что было отправлено

```python
from storage import load_sent_events

sent_map = load_sent_events(".")
print(sent_map)
# Вывод:
# {'@main_channel': {'channel_001:100', 'channel_001:101'}, 
#  '@archive_channel': {'channel_002:50', ...}}
```

---

## Структура хранилища

### Директория `sent/`

```
project_root/
  └── sent/
      ├── @my_channel.jsonl
      ├── @news.jsonl
      └── archive_channel.jsonl
```

### Формат записей

Каждая строка в файле - это JSON объект отправленного события:

```json
{
  "target": "@my_channel",
  "channel_id": "123456",
  "message_id": 789,
  "sent_at": "2026-04-19T15:30:00+00:00"
}
```

---

## Интеграция с расписанием (Cron)

### Ежедневная отправка новых событий (9:00)

```cron
0 9 * * * cd /home/user/projects/th-reader/bot && \
  python news_sender.py --target @news --report-days 3 --skip-sent >> cron.log 2>&1
```

### Еженедельная отправка всех событий (понедельник 12:00)

```cron
0 12 * * 1 cd /home/user/projects/th-reader/bot && \
  python news_sender.py --target @weekly --report-days 7 >> cron.log 2>&1
```

---

## API для разработчиков

### Проверить было ли событие отправлено

```python
from storage import load_sent_events

sent_map = load_sent_events(".", target_identifier="@my_channel")
event_key = f"{channel_id}:{message_id}"

if event_key in sent_map.get("@my_channel", set()):
    print("Событие уже было отправлено")
else:
    print("Событие новое")
```

### Получить события готовые к отправке

```python
from report_generator import generate_report_text
from processor_config_loader import load_processor_config

config = load_processor_config("config/processor_config.yaml")

pages = generate_report_text(
    report_config=config.report,
    base_path=".",
    results=None,
    load_from_storage=True,
    page_size_bytes=4096,
    target_identifier="@target",
    skip_already_sent=True,
    days=7,
)

# pages - это список текстовых страниц для отправки
for page in pages:
    print(f"Готов к отправке ({len(page)} символов):")
    print(page)
```

---

## Механизм работы

```
┌─────────────────────────────────────────────────────────────┐
│ Запуск news_sender.py                                       │
│ with --skip-sent flag                                       │
└────────────────┬──────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ load_processed_events_from_storage()                         │
│ Загружает все обработанные события за N дней                │
└────────────────┬──────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ load_sent_events(target_identifier)                          │
│ Загружает информацию об уже отправленных                    │
└────────────────┬──────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Filter out sent events                                      │
│ recent_events = [e for e if not in sent_map]               │
└────────────────┬──────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ _build_summary_text()                                        │
│ Форматирует события в текстовые страницы                    │
└────────────────┬──────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Send to Telegram                                             │
│ await client.send_message(entity, page)                      │
└────────────────┬──────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ mark_events_as_sent()                                        │
│ Записывает отправленные события в sent/                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Часто задаваемые вопросы

**Q: Что произойдет при удалении папки `sent/`?**
A: История отправок сбросится. При следующем запуске с `--skip-sent` события будут считаться новыми.

**Q: Можно ли отправить одно событие в разные каналы?**
A: Да! Каждый канал имеет собственную историю. Событие может быть отправлено в `@channel1`, затем в `@channel2`.

**Q: Что если скрипт упадет?**
A: События записываются ТОЛЬКО после успешной отправки. При ошибке события не будут помечены.

**Q: Как сбросить историю для одного события?**
A: Удалите запись из файла `sent/target_channel.jsonl` и переотправьте.

---

## Пример интеграции: Python код

```python
import asyncio
from news_sender import send_news_summary

async def main():
    # Отправить только новые события за последние 7 дней
    await send_news_summary(
        app_config_path="config/app.yaml",
        processor_config_path="config/processor_config.yaml",
        base_path=".",
        target="@my_news_channel",
        report_days=7,
        skip_already_sent=True,
    )

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Заключение

Новая система отслеживания позволяет:
- ✓ Избегать дублирования при регулярных отправках
- ✓ Управлять разной глубиной поиска для разных каналов
- ✓ Легко сбросить состояние если нужна переотправка
- ✓ Обеспечить уверенность в том, какие события были опубликованы

Все изменения **полностью обратно совместимы** - старый код продолжает работать без флага `--skip-sent`.
