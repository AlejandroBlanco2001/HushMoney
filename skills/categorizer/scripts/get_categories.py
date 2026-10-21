"""
Return the canonical spending category list.
Output: {"categories": [{"slug": "food", "label": "Food & Dining", "keywords": [...]}]}
"""
import json

CATEGORIES = [
    {
        "slug": "food",
        "label": "Food & Dining",
        "keywords": ["restaurante", "comida", "uber eats", "rappi", "ifood", "dominos",
                     "mcdonalds", "starbucks", "subway", "sushi", "pizza", "almuerzo",
                     "desayuno", "cena", "cafe", "panaderia", "supermercado", "exito",
                     "carulla", "jumbo", "olimpica", "ara", "d1", "mercado"],
    },
    {
        "slug": "transport",
        "label": "Transport",
        "keywords": ["uber", "taxi", "cabify", "indriver", "gasolina", "combustible",
                     "parqueadero", "estacionamiento", "peaje", "bus", "metro", "sitp",
                     "transmilenio", "mio", "tpaga", "autobus", "tren"],
    },
    {
        "slug": "entertainment",
        "label": "Entertainment",
        "keywords": ["netflix", "spotify", "disney", "hbo", "amazon prime", "youtube",
                     "cine", "teatro", "concierto", "evento", "steam", "playstation",
                     "nintendo", "xbox", "prime video", "apple tv", "paramount"],
    },
    {
        "slug": "health",
        "label": "Health",
        "keywords": ["farmacia", "pharmacy", "drogueria", "droga", "medico", "doctor",
                     "clinica", "hospital", "laboratorio", "optometria", "gafas",
                     "gym", "gimnasio", "smartfit", "bodytech"],
    },
    {
        "slug": "shopping",
        "label": "Shopping",
        "keywords": ["amazon", "mercadolibre", "falabella", "alkosto", "ktronix",
                     "zara", "h&m", "ropa", "calzado", "zapatillas", "tienda",
                     "bershka", "pull&bear", "adidas", "nike", "apple store"],
    },
    {
        "slug": "services",
        "label": "Services & Utilities",
        "keywords": ["epm", "codensa", "acueducto", "gas", "claro", "movistar",
                     "tigo", "wom", "internet", "telefono", "seguro", "insurance",
                     "alquiler", "arriendo", "administracion"],
    },
    {
        "slug": "transfers",
        "label": "Transfers",
        "keywords": ["transferencia", "transfer", "envio", "nequi", "daviplata",
                     "bancolombia a la mano"],
    },
    {
        "slug": "cash",
        "label": "Cash Withdrawal",
        "keywords": ["cajero", "atm", "retiro", "efectivo"],
    },
    {
        "slug": "other",
        "label": "Other",
        "keywords": [],
    },
]

print(json.dumps({"categories": CATEGORIES}))
