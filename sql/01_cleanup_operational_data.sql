BEGIN;

TRUNCATE TABLE
    request_log,
    bike_log,
    master_assignment,
    repair_parts_used,
    repair_required_parts,
    bike_replacement,
    repair_report,
    repair_request,
    rental,
    incoming_request,
    bike,
    spare_part_stock
RESTART IDENTITY CASCADE;

COMMIT;
