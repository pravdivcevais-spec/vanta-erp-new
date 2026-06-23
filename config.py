ROLE_LABELS = {
    "curator": "Куратор / Даркстор",
    "dispatcher": "Диспетчер",
    "field_master": "Выездной мастер",
    "workshop_master": "Мастер цеха",
    "senior_workshop": "Старший мастер цеха",
    "warehouse": "Склад",
}

EMPLOYEE_ROLE_MAP = {
    "dispatcher": ("диспетчер",),
    "field_master": ("выездной_мастер",),
    "workshop_master": ("мастер_цеха",),
    "senior_workshop": ("старший_мастер_цеха",),
    "warehouse": ("кладовщик",),
}

ACTIVE_REQUEST_STATUSES = {"новая", "назначена", "в работе", "отложена", "ожидает запчасти", "замена_вело", "замена вело"}
ACTIVE_MASTER_STATUSES = {"назначена", "в работе", "отложена", "ожидает запчасти", "замена вело"}
DONE_REQUEST_STATUSES = {"завершена", "отменена", "отменена_куратором", "отменена_админом"}
