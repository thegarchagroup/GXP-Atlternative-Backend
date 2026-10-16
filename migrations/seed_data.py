"""Reference data seeded once on an empty database. No accounts or secrets."""

ROOM_TYPES = [
    ("Standard", "Guest room", "Standard king or twin room"),
    ("Deluxe", "Guest room", "Larger room with minibar and safe"),
    ("Suite", "Suite", "Separate living area"),
]

# (name, category, mandatory, allow_na)
HOUSEKEEPING_CLEANING = [
    ("Strip and remake bed with fresh linen", "Bedroom", True, False),
    ("Dust all surfaces and furniture", "Bedroom", True, False),
    ("Vacuum or mop floors", "Bedroom", True, False),
    ("Empty bins and replace liners", "Bedroom", True, False),
    ("Clean and sanitise toilet", "Bathroom", True, False),
    ("Clean shower, bath and washbasin", "Bathroom", True, False),
    ("Clean mirrors and glass", "Bathroom", True, False),
    ("Replenish towels and toiletries", "Bathroom", True, False),
    ("Restock minibar", "Amenities", False, True),
]

HOUSEKEEPING_INSPECTION = [
    ("Bed and linen", "Room and furniture", True, False),
    ("Mattress and headboard", "Room and furniture", True, False),
    ("Wardrobe and hangers", "Room and furniture", True, False),
    ("Desk and chair", "Room and furniture", True, False),
    ("Curtains and windows", "Room and furniture", True, False),
    ("Floor and surfaces", "Room and furniture", True, False),
    ("Lights and switches", "Room and furniture", True, False),
    ("Electrical sockets", "Room and furniture", True, False),
    ("Air conditioning", "Appliances", True, False),
    ("Thermostat", "Appliances", True, False),
    ("Fan", "Appliances", False, True),
    ("Television", "Appliances", True, False),
    ("Remote controls", "Appliances", True, False),
    ("Refrigerator or minibar", "Appliances", False, True),
    ("Telephone", "Appliances", False, True),
    ("Electronic room safe", "Appliances", False, True),
    ("Toilet flush", "Bathroom", True, False),
    ("Toilet seat and condition", "Bathroom", True, False),
    ("Shower", "Bathroom", True, False),
    ("Water pressure", "Bathroom", True, False),
    ("Hot and cold water", "Bathroom", True, False),
    ("Washbasin", "Bathroom", True, False),
    ("Drainage", "Bathroom", True, False),
    ("Taps and fittings", "Bathroom", True, False),
    ("Bathroom lights", "Bathroom", True, False),
    ("Exhaust fan", "Bathroom", True, False),
    ("Mirrors", "Bathroom", True, False),
    ("Towels and toiletries", "Bathroom", True, False),
    ("Smoke detector", "Safety", True, False),
    ("Door lock", "Safety", True, False),
    ("Door closer", "Safety", True, False),
    ("Emergency instructions", "Safety", True, False),
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
