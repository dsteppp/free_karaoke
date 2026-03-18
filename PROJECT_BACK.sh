#!/bin/bash

OUTPUT="PROJECT_BACK.txt"

# Очищаем файл, если он уже существовал от предыдущих запусков
> "$OUTPUT"

# Задаем папки для исключения по умолчанию
EXCLUDE_DIRS=("cache" ".venv" "models" "library")

# Сообщаем пользователю о базовых исключениях и запрашиваем дополнительные
echo "По умолчанию из сканирования исключены папки: ${EXCLUDE_DIRS[*]}"
echo "Введите ДОПОЛНИТЕЛЬНЫЕ названия папок, которые нужно пропустить (через пробел), или просто нажмите Enter для продолжения:"
read -r -a USER_EXCLUDES

# Добавляем введенные пользователем папки в общий массив исключений
EXCLUDE_DIRS+=("${USER_EXCLUDES[@]}")

# Формируем массив аргументов для команды find
FIND_ARGS=()
for dir in "${EXCLUDE_DIRS[@]}"; do
    FIND_ARGS+=( -name "$dir" -prune -o )
done

echo "Начинаю сканирование проекта..."

# Поиск всех файлов. Игнорируем файлы, в названии которых есть _back
find . "${FIND_ARGS[@]}" -type f ! -iname "*_back*" -print0 | while IFS= read -r -d '' file; do
    
    # Пропускаем сам этот скрипт и итоговый файл
    if [[ "$file" == "./$OUTPUT" || "$file" == "$OUTPUT" || "$file" == "./$(basename "$0")" ]]; then
        continue
    fi

    is_text=false
    
    # 1. Проверка по списку расширений
    case "$file" in
        *.py|*.sh|*.js|*.mjs|*.cjs|*.ts|*.jsx|*.tsx|*.css|*.scss|*.sass|*.less|*.html|*.htm|*.txt|*.md|*.csv|*.json|*.xml|*.yml|*.yaml|*.ini|*.conf|*.php|*.rb|*.java|*.c|*.cpp|*.h|*.hpp|*.go|*.rs|*.sql|*.env|*.svg|*.vue|*.svelte|*.astro)
            is_text=true
            ;;
        *)
            # 2. Проверка mime-кодировки для файлов без известных расширений
            encoding=$(file -b --mime-encoding "$file")
            if [[ "$encoding" != "binary" && "$encoding" != "unknown-8bit" ]]; then
                is_text=true
            fi
            ;;
    esac

    # Если файл признан текстовым, записываем его
    if [ "$is_text" = true ]; then
        echo "================================================================================" >> "$OUTPUT"
        echo "ФАЙЛ: $file" >> "$OUTPUT"
        echo "================================================================================" >> "$OUTPUT"
        cat "$file" >> "$OUTPUT"
        echo -e "\n" >> "$OUTPUT"
    fi

done

echo "Сбор файлов успешно завершен! Результат сохранен в корень проекта: $OUTPUT"
