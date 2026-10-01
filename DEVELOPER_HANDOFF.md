# Backend — передача разработчикам, 1 октября 2026

Рабочая ветка: `feat/current-game`. `main` и прежний `develop` сохранены.
Теги `archive/original-2026-09-15` и `archive/github-before-2026-10-01` фиксируют
исходный код и предыдущую GitHub-версию. Продолжаем от новой рабочей ветки.

[Полная инструкция, материалы и результаты проверок](https://github.com/karapetsevak4-blip/versus-frontend/blob/feat/current-game/DEVELOPER_HANDOFF.md)

[Frontend игры](https://github.com/karapetsevak4-blip/versus-frontend/tree/feat/current-game)
и [демо дизайна](https://github.com/karapetsevak4-blip/versus-frontend/tree/demo/pixel-terminal)
разделены: демо выполняет операции в браузере и не подключено к этому API.

## Текущая реализация

Сохранены атомарные игровые операции/регистрация, начисление по времени,
каталог, статистика команд и последняя UI-интеграция: обучение, задания,
история и operation receipts. Миграция 0029 включена. Коммит интеграции: `c2ca9b0`.
Реальные Telegram/Stars/withdrawal/сезонные итоги не объявлены готовыми.
Перед миграцией общего окружения нужны backup и отдельное разрешение на deploy.

## Проверки

01.10.2026: 129 PostgreSQL tests — OK, без пропусков; SQLite 129 — OK,
20 пропусков PostgreSQL-проверок; Django check и migration drift — OK.
Сохранены предупреждения W340 для двух ManyToManyField и staticfiles в тестах.
Команды установки и SQLite-проверок приведены в README.md.

Локальный PostgreSQL/Redis стенд ожидает структуру общего workspace:
`code/Versus-main`, `code/tma-versus-main`, `deployment/local`, `.local`.
Скрипты и инструкция находятся во frontend `project/deployment/local/`;
не переносите приватные runtime/пароли/БД владельца. Используйте отдельную
тестовую БД. CI запускает SQLite/check/migration drift; приведённый результат
PostgreSQL получен локально. Push этой ветки запускает CI, но не deploy.
