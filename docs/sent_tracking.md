# Отслеживание отправленных сообщений

## Введение

Система теперь может отслеживать какие события уже были отправлены в целевой канал, чтобы избежать повторной публикации одних и тех же новостей.

## Архитектура

### Хранилище отправленных событий (`sent/`)

События записываются в формате JSONL по целевым каналам:
```
sent/
  ├── @my_channel.jsonl
  ├── @news_channel.jsonl
  └── my_channel_id.jsonl
```

Каждая запись содержит:
```json
{
  "target": "@my_channel",
  "channel_id": "12345",
  "message_id": 998,
  "sent_at": "2026-04-19T15:30:00+00:00"
}
```

### Компоненты

| Модуль | Функция | Назначение |
|--------|---------|-----------|
| `storage.py` | `mark_events_as_sent()` | Записать отправленные события |
| `storage.py` | `load_sent_events()` | Загрузить историю отправок |
| `report_generator.py` | `generate_report_text()` | Генерировать отчет с фильтрацией |
| `news_sender.py` | `send_news_summary()` | Отправить и зафиксировать |

## Использование

### Базовое использование - отправить все события

```bash
python news_sender.py --target @my_channel --report-days 7
```

Отправляет ВСЕ события за последние 7 дней, включая уже отправленные.

### Пропустить уже отправленные

```bash
python news_sender.py --target @my_channel --report-days 7 --skip-sent
```

Отправляет ТОЛЬКО события, которые еще не были отправлены этому каналу.

### Переопределить глубину поиска

```bash
python news_sender.py --target @my_channel --report-days 14 --skip-sent
```

Ищет события за последние 14 дней, исключая уже отправленные.

## Сценарии использования

### Сценарий 1: Регулярная отправка новых событий

Каждый день отправляем только новые события за последние 3 дня:

```bash
# Каждый день в 09:00
python news_sender.py --target @news_channel --report-days 3 --skip-sent
```

**Результат**: Каждый день отправляются только новые события, уже опубликованные пропускаются.

### Сценарий 2: Переотправка всех последних событий

Отправляем все события за неделю (даже если были отправлены):

```bash
python news_sender.py --target @news_channel --report-days 7
```

**Результат**: Все события за 7 дней отправляются повторно.

### Сценарий 3: Проверка + отправка в разные каналы

```bash
# Отправить в основной канал (только новые)
python news_sender.py --target @main_channel --report-days 7 --skip-sent

# Отправить в архив-канал (все)
python news_sender.py --target @archive_channel --report-days 30
```

**Результат**: Разные каналы получают разные наборы событий.

## API для разработчиков

### mark_events_as_sent()

```python
from storage import mark_events_as_sent

events = [
    {"channel_id": "12345", "message_id": 100},
    {"channel_id": "12345", "message_id": 101},
]

mark_events_as_sent(
    base_path="/path/to/project",
    target_identifier="@my_channel",
    event_ids=events,
)
```

### load_sent_events()

```python
from storage import load_sent_events

# Загрузить все отправки в любой канал
sent_map = load_sent_events("/path/to/project")
# Результат: {"@channel1": {"12345:100", "12345:101"}, "@channel2": {...}}

# Загрузить отправки в конкретный канал
sent_map = load_sent_events("/path/to/project", target_identifier="@my_channel")
# Результат: {"@my_channel": {"12345:100", "12345:101"}}

# Проверить было ли событие отправлено
if "12345:100" in sent_map.get("@my_channel", set()):
    print("Событие уже отправлено")
```

### generate_report_text() с фильтрацией

```python
from report_generator import generate_report_text

pages = generate_report_text(
    report_config=config,
    base_path="/path/to/project",
    results=None,
    load_from_storage=True,
    page_size_bytes=4096,
    target_identifier="@my_channel",
    skip_already_sent=True,
    days=7,
)
```

## Интеграция с расписанием (Cron)

### Пример crontab для ежедневной отправки

```cron
# Каждый день в 9:00 - отправить новые события за 3 дня
0 9 * * * cd /path/to/project && python news_sender.py --target @news --report-days 3 --skip-sent >> cron.log 2>&1

# Каждый понедельник в 12:00 - переотправить все за неделю
0 12 * * 1 cd /path/to/project && python news_sender.py --target @weekly_summary --report-days 7 >> cron.log 2>&1
```

## Отладка

### Посмотреть что было отправлено

```bash
# Посмотреть файл отправок
cat sent/@my_channel.jsonl
```

### Удалить историю отправок (сбросить состояние)

```bash
# Для одного канала
rm sent/@my_channel.jsonl

# Для всех каналов
rm -rf sent/
```

### Логирование

Включите DEBUG логирование для подробной информации:

```bash
python news_sender.py --target @my_channel --log-level DEBUG
```

## Часто задаваемые вопросы

**Q: Что произойдет если удалить папку `sent/`?**  
A: История отправок сбросится, и все события будут считаться новыми. При следующем запуске с `--skip-sent` отправятся все события.

**Q: Могу ли я отправлять одни и те же события в разные каналы?**  
A: Да! Каждый канал имеет свою историю отправок. Вы можете отправить событие в `@channel1` и затем в `@channel2`, и каждый будет знать только о своих отправках.

**Q: Как изменить сообщение после отправки?**  
A: Нельзя напрямую, но можно:
1. Удалить запись из `sent/` для конкретного события
2. Отправить исправленную версию

**Q: Что если процесс упадет во время отправки?**  
A: События записываются ПОСЛЕ успешной отправки, поэтому если произойдет ошибка до завершения, события не будут помечены как отправленные.

**Q: Может ли быть дублирование если запустить скрипт дважды подряд?**  
A: С флагом `--skip-sent` - нет. События, отправленные в первом запуске, будут пропущены во втором.

## Примеры интеграции

### Python API

```python
import asyncio
from news_sender import send_news_summary

asyncio.run(send_news_summary(
    app_config_path="config/app.yaml",
    processor_config_path="config/processor_config.yaml",
    base_path=".",
    target="@my_channel",
    report_days=7,
    skip_already_sent=True,
))
```

### Docker

```dockerfile
# Отправить новые события каждый день в 9:00
CMD ["crond", "-f"]
# + cron job в контейнере
```

## Мониторинг и статистика

Для отслеживания количества отправленных событий:

```python
from storage import load_sent_events

sent_map = load_sent_events(".")
for target, event_ids in sent_map.items():
    print(f"{target}: {len(event_ids)} отправлено")
```

