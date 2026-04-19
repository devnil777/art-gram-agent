#!/usr/bin/env python3
"""
Example: Tracking sent events with news_sender.py

This example demonstrates how to use the new event tracking features.
"""

import sys
import os

# Добавить путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage import mark_events_as_sent, load_sent_events
from report_generator import generate_report_text, load_processed_events_from_storage
from processor_config_loader import load_processor_config

def example_1_mark_events_as_sent():
    """Пример 1: Записать отправленные события"""
    print("\n" + "="*60)
    print("Пример 1: Записать отправленные события")
    print("="*60)
    
    # События которые были отправлены
    events_to_mark = [
        {"channel_id": "channel_001", "message_id": 100},
        {"channel_id": "channel_001", "message_id": 101},
        {"channel_id": "channel_002", "message_id": 50},
    ]
    
    # Записать что эти события были отправлены в канал @news
    mark_events_as_sent(
        base_path=".",
        target_identifier="@news",
        event_ids=events_to_mark,
    )
    
    print("✓ Записано 3 события как отправленные в @news")


def example_2_load_sent_events():
    """Пример 2: Загрузить информацию об отправленных событиях"""
    print("\n" + "="*60)
    print("Пример 2: Загрузить информацию об отправленных")
    print("="*60)
    
    # Загрузить все отправки
    sent_map = load_sent_events(".")
    
    print(f"\nВсего целевых каналов: {len(sent_map)}")
    for target, event_ids in sent_map.items():
        print(f"\n  {target}:")
        print(f"    Отправлено событий: {len(event_ids)}")
        
        # Показать первые несколько
        for i, event_id in enumerate(list(event_ids)[:3], 1):
            print(f"      {i}. {event_id}")
        
        if len(event_ids) > 3:
            print(f"      ... и еще {len(event_ids) - 3}")


def example_3_filter_unsent_events():
    """Пример 3: Получить только непубликованные события"""
    print("\n" + "="*60)
    print("Пример 3: Получить только непубликованные события")
    print("="*60)
    
    # Загрузить конфиг
    processor_config = load_processor_config("config/processor_config.yaml")
    
    # Получить события за последние 7 дней, исключая уже отправленные
    pages = generate_report_text(
        report_config=processor_config.report,
        base_path=".",
        results=None,
        load_from_storage=True,
        page_size_bytes=4096,
        target_identifier="@news",
        skip_already_sent=True,  # <- Важный параметр!
        days=7,
    )
    
    print(f"\nНайдено непубликованных событий за 7 дней:")
    print(f"  Всего страниц: {len(pages)}")
    
    total_chars = sum(len(p) for p in pages)
    print(f"  Всего символов: {total_chars}")
    
    # Показать первую страницу
    if pages:
        print(f"\n  Первая страница (первые 200 символов):")
        print("  " + "-"*50)
        preview = pages[0][:200].replace("\n", "\n  ")
        print("  " + preview + ("..." if len(pages[0]) > 200 else ""))
        print("  " + "-"*50)


def example_4_check_event_sent():
    """Пример 4: Проверить было ли событие отправлено"""
    print("\n" + "="*60)
    print("Пример 4: Проверить отправку конкретного события")
    print("="*60)
    
    # Загрузить отправки для целевого канала
    sent_map = load_sent_events(".", target_identifier="@news")
    sent_ids = sent_map.get("@news", set())
    
    # События для проверки
    test_events = [
        ("channel_001", 100),
        ("channel_001", 999),  # Этот скорее всего не был отправлен
    ]
    
    for channel_id, message_id in test_events:
        event_key = f"{channel_id}:{message_id}"
        was_sent = event_key in sent_ids
        status = "✓ ДА" if was_sent else "✗ НЕТ"
        print(f"\n  {event_key}: {status}")


def example_5_stats():
    """Пример 5: Статистика отправок"""
    print("\n" + "="*60)
    print("Пример 5: Статистика отправок")
    print("="*60)
    
    # Загрузить все отправки
    sent_map = load_sent_events(".")
    
    if not sent_map:
        print("\n  Нет отправленных событий")
        return
    
    print("\n  Статистика по каналам:")
    print("  " + "-"*40)
    
    total_sent = 0
    for target in sorted(sent_map.keys()):
        count = len(sent_map[target])
        total_sent += count
        print(f"  {target:20} {count:4} событий")
    
    print("  " + "-"*40)
    print(f"  {'ИТОГО':20} {total_sent:4} событий")


def print_usage():
    """Печать справки"""
    print("""
Примеры использования отслеживания отправленных событий

Использование:
    python example_sent_tracking.py [номер_примера]

Доступные примеры:
    1 - Записать отправленные события
    2 - Загрузить информацию об отправленных
    3 - Получить только непубликованные события
    4 - Проверить отправку конкретного события
    5 - Статистика отправок
    all - Запустить все примеры

Примеры:
    python example_sent_tracking.py 1
    python example_sent_tracking.py all
    """)


if __name__ == "__main__":
    example_num = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    examples = {
        "1": example_1_mark_events_as_sent,
        "2": example_2_load_sent_events,
        "3": example_3_filter_unsent_events,
        "4": example_4_check_event_sent,
        "5": example_5_stats,
    }
    
    if example_num == "all":
        for example_func in examples.values():
            try:
                example_func()
            except Exception as e:
                print(f"\n✗ Ошибка в примере: {e}")
    elif example_num in examples:
        try:
            examples[example_num]()
        except Exception as e:
            print(f"\n✗ Ошибка: {e}")
    else:
        print(f"✗ Неизвестный пример: {example_num}")
        print_usage()
        sys.exit(1)
    
    print("\n" + "="*60)
    print("Примеры завершены")
    print("="*60 + "\n")
