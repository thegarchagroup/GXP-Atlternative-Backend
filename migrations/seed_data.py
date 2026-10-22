"""Reference data seeded once on an empty database. No accounts or secrets."""

ROOM_TYPES = [
    ("Standard", "Guest room", "Standard king or twin room"),
    ("Deluxe", "Guest room", "Larger room with minibar and safe"),
    ("Suite", "Suite", "Separate living area"),
]

# (name, category, mandatory, allow_na)
# The room attendant's form has two simple sections. The HK supervisor can add or remove items anytime.
HOUSEKEEPING_CLEANING = [
    ("Make bed with fresh linen", "Cleaning", True, False),
    ("Dust surfaces and furniture", "Cleaning", True, False),
    ("Vacuum or mop floors", "Cleaning", True, False),
    ("Empty bins and replace liners", "Cleaning", True, False),
    ("Clean and sanitise toilet", "Cleaning", True, False),
    ("Clean shower and washbasin", "Cleaning", True, False),
    ("Clean mirrors and glass", "Cleaning", True, False),
    ("Replenish towels and toiletries", "Cleaning", True, False),
    ("Restock minibar", "Cleaning", False, True),
]

HOUSEKEEPING_INSPECTION = [
    ("Air conditioning", "Engineering items", True, False),
    ("Lights and switches", "Engineering items", True, False),
    ("Television", "Engineering items", True, False),
    ("Toilet flush", "Engineering items", True, False),
    ("Shower", "Engineering items", True, False),
    ("Washbasin", "Engineering items", True, False),
    ("Drainage", "Engineering items", True, False),
    ("Mirrors", "Engineering items", True, False),
    ("Door lock", "Engineering items", True, False),
    ("Door closer", "Engineering items", True, False),
    ("Smoke detector", "Engineering items", True, False),
    ("Fan", "Engineering items", False, True),
]

ENGINEERING_INSPECTION = [
    ("Air conditioning operational", "HVAC", True, True),
    ("Fan operational", "HVAC", False, True),
    ("Electrical fittings safe", "Electrical", True, False),
    ("Lights and switches operational", "Electrical", True, False),
    ("Flush working", "Plumbing", True, True),
    ("Plumbing leaks resolved", "Plumbing", True, True),
    ("Water supply functional", "Plumbing", True, True),
    ("Drainage functional", "Plumbing", True, True),
    ("Door lock operational", "Safety", True, False),
    ("Safety devices operational", "Safety", True, False),
    ("Repair work area safe and clear", "General", True, False),
]
