BEGIN;

ALTER TABLE bike
ALTER COLUMN darkstore_id DROP NOT NULL;

INSERT INTO bike (
    id,
    serial_number,
    gov_number,
    model,
    location_status,
    tech_status,
    holder_type,
    holder_id,
    darkstore_id,
    purchase_price,
    purchase_date,
    days_in_rent,
    iot_device_id,
    created_at,
    updated_at
) VALUES
    (1, 'VNT-001', 'А101АА', 'City 2.0', 'В аренде', 'Ожидает выездного ремонта', 'B2B', 1, 1, 78000, DATE '2025-01-10', 14, 'IOT-001', NOW(), NOW()),
    (2, 'VNT-002', 'А202АА', 'City 2.0', 'В аренде', 'Исправен', 'B2B', 2, 1, 78000, DATE '2025-01-12', 29, 'IOT-002', NOW(), NOW()),
    (3, 'VNT-003', 'В303ВВ', 'Urban Pro', 'В аренде', 'Ожидает выездного ремонта', 'B2B', 3, 2, 82000, DATE '2025-02-01', 9, 'IOT-003', NOW(), NOW()),
    (4, 'VNT-004', 'В404ВВ', 'Urban Pro', 'В аренде', 'В ремонте', 'B2B', 4, 3, 82000, DATE '2025-02-05', 6, 'IOT-004', NOW(), NOW()),
    (5, 'VNT-005', 'С505СС', 'Cargo Lite', 'В аренде', 'Исправен', 'B2B', 5, 4, 93000, DATE '2025-02-15', 33, 'IOT-005', NOW(), NOW()),
    (6, 'VNT-006', 'С606СС', 'Cargo Lite', 'Свободен', 'Ожидает ремонта', 'stock', NULL, NULL, 93000, DATE '2025-02-20', 0, 'IOT-006', NOW(), NOW()),
    (7, 'VNT-007', 'Е707ЕЕ', 'Street Neo', 'Свободен', 'Исправен', 'stock', NULL, NULL, 76000, DATE '2025-03-03', 0, 'IOT-007', NOW(), NOW()),
    (8, 'VNT-008', 'Е808ЕЕ', 'Street Neo', 'Свободен', 'В ремонте', 'stock', NULL, NULL, 76000, DATE '2025-03-10', 0, 'IOT-008', NOW(), NOW());

SELECT setval('public.bike_id_seq', (SELECT MAX(id) FROM bike));

INSERT INTO rental (
    id,
    bike_id,
    client_id,
    start_dt,
    end_dt,
    days_count,
    status,
    created_at,
    updated_at
) VALUES
    (1, 1, 1, NOW() - INTERVAL '14 day', NULL, 14, 'активна', NOW(), NOW()),
    (2, 2, 2, NOW() - INTERVAL '29 day', NULL, 29, 'активна', NOW(), NOW()),
    (3, 3, 3, NOW() - INTERVAL '9 day', NULL, 9, 'активна', NOW(), NOW()),
    (4, 4, 4, NOW() - INTERVAL '6 day', NULL, 6, 'активна', NOW(), NOW()),
    (5, 5, 5, NOW() - INTERVAL '33 day', NULL, 33, 'активна', NOW(), NOW());

SELECT setval('public.rental_id_seq', (SELECT MAX(id) FROM rental));

INSERT INTO incoming_request (
    id,
    request_date,
    request_type,
    direction,
    darkstore_id,
    bike_id,
    problem,
    status,
    master_id,
    start_work,
    end_work,
    chat_id,
    full_address,
    curator_name,
    device_type,
    repeat_count,
    created_at,
    updated_at
) VALUES
    (1, NOW() - INTERVAL '2 day', 'ремонт', 'север', 1, 1, 'Не работает мотор, нужна диагностика на точке', 'назначена', 1, NULL, NULL, 'seed-chat-001', 'Даркстор 1234, север', '1234', 'Велосипед', 0, NOW(), NOW()),
    (2, NOW() - INTERVAL '1 day', 'ремонт', 'юг', 2, 3, 'Тормоза работают с задержкой', 'новая', NULL, NULL, NULL, 'seed-chat-002', 'Даркстор 6688, юг', '6688', 'Велосипед', 0, NOW(), NOW()),
    (3, NOW() - INTERVAL '8 hour', 'ремонт', 'запад', 3, 4, 'Проколота камера, мастер уже на точке', 'в работе', 1, NOW() - INTERVAL '4 hour', NULL, 'seed-chat-003', 'Даркстор 1478, запад', '1478', 'Велосипед', 0, NOW(), NOW()),
    (4, NOW() - INTERVAL '5 hour', 'ремонт', 'восток', 4, NULL, 'Диагностика аккумулятора курьерского комплекта', 'новая', NULL, NULL, NULL, 'seed-chat-004', 'Даркстор 3897, восток', '3897', 'аккумулятор', 0, NOW(), NOW()),
    (5, NOW() - INTERVAL '3 day', 'ремонт', 'восток', 4, 5, 'Плановая проверка завершена успешно', 'завершена', 1, NOW() - INTERVAL '2 day', NOW() - INTERVAL '1 day', 'seed-chat-005', 'Даркстор 3897, восток', '3897', 'Велосипед', 0, NOW(), NOW());

SELECT setval('public.incoming_request_id_seq', (SELECT MAX(id) FROM incoming_request));

INSERT INTO repair_request (
    id,
    bike_id,
    incoming_id,
    status,
    type,
    postponed_reason,
    client_rating,
    client_comment,
    comment,
    created_at,
    updated_at
) VALUES
    (1, 1, 1, 'назначена', 'выездной ремонт', NULL, NULL, NULL, NULL, NOW(), NOW()),
    (2, 4, 3, 'в работе', 'выездной ремонт', NULL, NULL, NULL, 'Начата замена камеры на точке', NOW(), NOW()),
    (3, 5, 5, 'завершена', 'выездной ремонт', NULL, 5, 'Все хорошо', 'Выполнена регулировка тормозов и проверка электрики', NOW(), NOW()),
    (4, 6, NULL, 'в работе', 'внутренний ремонт', NULL, NULL, NULL, 'Цех принял велосипед после возврата, идет диагностика', NOW(), NOW()),
    (5, 8, NULL, 'назначена', 'сборка велосипеда', NULL, NULL, NULL, 'Новый велосипед подготовлен к сборке', NOW(), NOW());

SELECT setval('public.repair_request_id_seq', (SELECT MAX(id) FROM repair_request));

INSERT INTO master_assignment (
    id,
    repair_request_id,
    assigned_by,
    assigned_to,
    comment,
    assigned_at
) VALUES
    (1, 1, 2, 1, 'Назначение из диспетчерского потока северного направления', NOW() - INTERVAL '2 day'),
    (2, 2, 2, 1, 'Срочный выезд на западный парк', NOW() - INTERVAL '8 hour'),
    (3, 3, 2, 1, 'Плановая заявка на восток закрыта мастером', NOW() - INTERVAL '3 day'),
    (4, 4, 4, 4, 'Мастер цеха взял велосипед в работу', NOW() - INTERVAL '6 hour'),
    (5, 5, 4, 4, 'Поставлено в очередь на сборку', NOW() - INTERVAL '1 hour');

SELECT setval('public.master_assignment_id_seq', (SELECT MAX(id) FROM master_assignment));

INSERT INTO repair_parts_used (
    id,
    repair_request_id,
    spare_part_catalog_id,
    quantity_used,
    created_at
) VALUES
    (1, 3, 1, 1, NOW() - INTERVAL '1 day'),
    (2, 3, 3, 1, NOW() - INTERVAL '1 day');

SELECT setval('public.repair_parts_used_id_seq', (SELECT MAX(id) FROM repair_parts_used));

INSERT INTO spare_part_stock (
    id,
    spare_part_catalog_id,
    darkstore_id,
    quantity,
    updated_at
) VALUES
    (1, 1, 1, 14, NOW()),
    (2, 2, 1, 6, NOW()),
    (3, 3, 2, 11, NOW()),
    (4, 4, 3, 4, NOW()),
    (5, 5, 4, 2, NOW());

SELECT setval('public.spare_part_stock_id_seq', (SELECT MAX(id) FROM spare_part_stock));

COMMIT;
