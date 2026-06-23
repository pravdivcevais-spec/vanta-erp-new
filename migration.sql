-- =============================================================================
-- Vanta ERP — Migration Script
-- Запустите этот файл в Supabase: SQL Editor → вставьте текст → Run
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. НОВЫЕ ТАБЛИЦЫ: logistics_request + logistics_bike
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS logistics_request (
    id           SERIAL       PRIMARY KEY,
    request_type VARCHAR(20)  NOT NULL,                          -- 'вывоз' | 'поставка'
    darkstore_id INTEGER      REFERENCES darkstore(id) ON DELETE SET NULL,
    status       VARCHAR(50)  NOT NULL DEFAULT 'новая',          -- новая | назначена | выполнена
    assigned_to  INTEGER      REFERENCES employee(id)  ON DELETE SET NULL,
    created_by   INTEGER      REFERENCES employee(id)  ON DELETE SET NULL,
    notes        TEXT,
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS logistics_bike (
    id             SERIAL  PRIMARY KEY,
    logistics_id   INTEGER NOT NULL REFERENCES logistics_request(id) ON DELETE CASCADE,
    bike_id        INTEGER NOT NULL REFERENCES bike(id) ON DELETE CASCADE,
    UNIQUE (logistics_id, bike_id)
);


-- ---------------------------------------------------------------------------
-- 2. ПОЛЯ M4 В incoming_request (если ещё не добавлены)
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'incoming_request' AND column_name = 'source'
    ) THEN
        ALTER TABLE incoming_request ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'vanta';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'incoming_request' AND column_name = 'external_id'
    ) THEN
        ALTER TABLE incoming_request ADD COLUMN external_id VARCHAR(100) NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'incoming_request' AND column_name = 'deadline'
    ) THEN
        ALTER TABLE incoming_request ADD COLUMN deadline TIMESTAMP NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'incoming_request' AND column_name = 'priority'
    ) THEN
        ALTER TABLE incoming_request ADD COLUMN priority VARCHAR(50) NULL;
    END IF;
END $$;


-- ---------------------------------------------------------------------------
-- 3. ТЕСТОВЫЕ ДАРКТОРЫ
--    Замените названия и адреса на реальные ваши.
--    Если даркторы уже есть в базе — закомментируйте этот блок.
-- ---------------------------------------------------------------------------

INSERT INTO darkstore (name, direction, latitude, longitude)
VALUES
    ('Центр-1',         'Центральное',   55.7558,  37.6176),
    ('Центр-2',         'Центральное',   55.7612,  37.6089),
    ('Север-1',         'Северное',      55.8422,  37.5867),
    ('Север-2',         'Северное',      55.8301,  37.6234),
    ('Юг-1',            'Южное',         55.6744,  37.5891),
    ('Юг-2',            'Южное',         55.6612,  37.6412),
    ('Запад-1',         'Западное',      55.7301,  37.4567),
    ('Запад-2',         'Западное',      55.7456,  37.4123),
    ('Восток-1',        'Восточное',     55.7701,  37.7234),
    ('Восток-2',        'Восточное',     55.7589,  37.7567)
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------------------
-- 4. ТЕСТОВЫЕ ВЕЛОСИПЕДЫ
--    652 велосипеда — ниже 30 примеров для проверки интерфейса.
--    Для загрузки всех 652 используйте отдельный Excel-импорт или CSV.
--
--    Форматы гос номеров: 4 цифры, например 9085.
--    Модели: замените на ваши реальные.
--    location_status: 'Свободен' | 'В аренде' | 'Кража'
--    tech_status:     'Исправен' | 'Ожидает ремонта' | 'В ремонте'
--    holder_type:     'stock' (склад) | 'B2B' | 'B2C'
-- ---------------------------------------------------------------------------

-- Байки на складе (Свободен + Исправен) — готовы к поставке
INSERT INTO bike (serial_number, gov_number, model, location_status, tech_status, holder_type, holder_id, darkstore_id, purchase_price, purchase_date, days_in_rent, created_at, updated_at)
VALUES
    ('SN-10001', '1001', 'Stels Navigator 310', 'Свободен', 'Исправен', 'stock', NULL, NULL, 28000, '2023-03-15', 0, NOW(), NOW()),
    ('SN-10002', '1002', 'Stels Navigator 310', 'Свободен', 'Исправен', 'stock', NULL, NULL, 28000, '2023-03-15', 0, NOW(), NOW()),
    ('SN-10003', '1003', 'Forward Jade 2.0',    'Свободен', 'Исправен', 'stock', NULL, NULL, 31000, '2023-04-10', 0, NOW(), NOW()),
    ('SN-10004', '1004', 'Forward Jade 2.0',    'Свободен', 'Исправен', 'stock', NULL, NULL, 31000, '2023-04-10', 0, NOW(), NOW()),
    ('SN-10005', '1005', 'Author Stylo 2',       'Свободен', 'Исправен', 'stock', NULL, NULL, 26500, '2023-05-20', 0, NOW(), NOW()),
    ('SN-10006', '1006', 'Author Stylo 2',       'Свободен', 'Исправен', 'stock', NULL, NULL, 26500, '2023-05-20', 0, NOW(), NOW()),
    ('SN-10007', '1007', 'Trek FX 2',            'Свободен', 'Исправен', 'stock', NULL, NULL, 45000, '2023-06-01', 0, NOW(), NOW()),
    ('SN-10008', '1008', 'Trek FX 2',            'Свободен', 'Исправен', 'stock', NULL, NULL, 45000, '2023-06-01', 0, NOW(), NOW()),
    ('SN-10009', '1009', 'Stels Navigator 310', 'Свободен', 'Ожидает ремонта', 'stock', NULL, NULL, 28000, '2022-11-10', 0, NOW(), NOW()),
    ('SN-10010', '1010', 'Forward Jade 2.0',    'Свободен', 'Ожидает ремонта', 'stock', NULL, NULL, 31000, '2022-10-05', 0, NOW(), NOW())
ON CONFLICT (serial_number) DO NOTHING;

-- Байки на дарксторах (В аренде, B2B) — нужны реальные darkstore_id
-- Замените (SELECT id FROM darkstore WHERE name = '...') на нужные вам
INSERT INTO bike (serial_number, gov_number, model, location_status, tech_status, holder_type, darkstore_id, purchase_price, purchase_date, days_in_rent, created_at, updated_at)
SELECT
    'SN-2' || lpad(n::text, 4, '0'),
    (9000 + n)::text,
    CASE (n % 4)
        WHEN 0 THEN 'Stels Navigator 310'
        WHEN 1 THEN 'Forward Jade 2.0'
        WHEN 2 THEN 'Author Stylo 2'
        ELSE        'Trek FX 2'
    END,
    'В аренде',
    'Исправен',
    'B2B',
    (SELECT id FROM darkstore ORDER BY id LIMIT 1 OFFSET (n % 10)),
    CASE (n % 4)
        WHEN 0 THEN 28000
        WHEN 1 THEN 31000
        WHEN 2 THEN 26500
        ELSE        45000
    END,
    '2023-01-01'::date + (n * 3 || ' days')::interval,
    (n % 180),
    NOW(), NOW()
FROM generate_series(1, 20) AS n
ON CONFLICT (serial_number) DO NOTHING;


-- ---------------------------------------------------------------------------
-- 5. ПРОВЕРКА — сколько записей в каждой таблице
-- ---------------------------------------------------------------------------

SELECT 'darkstore'         AS table_name, COUNT(*) FROM darkstore
UNION ALL
SELECT 'bike',              COUNT(*) FROM bike
UNION ALL
SELECT 'logistics_request', COUNT(*) FROM logistics_request
UNION ALL
SELECT 'logistics_bike',    COUNT(*) FROM logistics_bike;
