"""General Knowledge and Reference Library for Black Intel AI Assistant.

Provides curated, verified, legally usable reference knowledge across Science,
Mathematics, Computer Science & Programming, Cybersecurity, History, Geography,
and Problem Solving. Enables rich, natural answers in Gemini-free and local modes.
"""

import re
from typing import Any

# Curated reference knowledge entries with topical keywords and verified explanations
GENERAL_KNOWLEDGE_RECORDS = (
    # --- PROGRAMMING & COMPUTER SCIENCE ---
    {
        "id": "gen-python-add-numbers",
        "category": "programming",
        "topic": "Python Function: Add Two Numbers",
        "keywords": ("python", "function", "add", "numbers", "sum", "two", "arguments", "parameters", "plus"),
        "summary": "How to define a Python function that adds two numbers.",
        "content": (
            "In Python, you define a function using the `def` keyword. Here is a clean, typed implementation that adds two numbers:\n\n"
            "```python\n"
            "def add_numbers(a: float | int, b: float | int) -> float | int:\n"
            '    """Return the sum of two numbers a and b."""\n'
            "    return a + b\n\n"
            "# Example usage:\n"
            "result = add_numbers(5, 7)\n"
            'print(f"The sum is: {result}")  # Output: The sum is: 12\n'
            "```\n\n"
            "**Key Details:**\n"
            "- `def add_numbers(a, b)`: Declares the function and its parameters.\n"
            "- Type annotations (`float | int`) clarify acceptable argument and return types.\n"
            "- The `+` operator computes the arithmetic sum."
        ),
        "source": "Python 3 Standard Documentation",
    },
    {
        "id": "gen-python-basics",
        "category": "programming",
        "topic": "Python Programming Language Overview",
        "keywords": ("python", "programming", "language", "syntax", "code", "coding", "developer"),
        "summary": "Core features and design philosophy of Python.",
        "content": (
            "Python is a high-level, interpreted, general-purpose programming language created by Guido van Rossum. "
            "It emphasizes code readability with significant indentation.\n\n"
            "**Core Features:**\n"
            "- **Dynamically Typed:** Variable types are checked at runtime.\n"
            "- **Multi-Paradigm:** Supports object-oriented, functional, and procedural programming.\n"
            "- **Extensive Standard Library:** Built-in support for networking, math, string parsing, JSON, and file I/O.\n"
            "- **Popular Uses:** Web development (Flask, Django, FastAPI), Artificial Intelligence / Machine Learning "
            "(PyTorch, TensorFlow), Automation, Data Science, and Cybersecurity scripting."
        ),
        "source": "Python Software Foundation (python.org)",
    },
    {
        "id": "gen-python-reverse-string",
        "category": "programming",
        "topic": "Reversing a String in Python",
        "keywords": ("python", "reverse", "string", "slice", "slicing", "reversed"),
        "summary": "Methods to reverse a string in Python.",
        "content": (
            "In Python, the most idiomatic and efficient way to reverse a string is using extended slicing:\n\n"
            "```python\n"
            "def reverse_string(s: str) -> str:\n"
            '    """Reverse the given string using slicing."""\n'
            "    return s[::-1]\n\n"
            "# Example:\n"
            'text = "Black Intel"\n'
            "reversed_text = reverse_string(text)\n"
            'print(reversed_text)  # Output: letnI kcalB\n'
            "```\n\n"
            "**Alternative using `reversed()`:**\n"
            "```python\n"
            'reversed_text = "".join(reversed(text))\n'
            "```"
        ),
        "source": "Python Language Reference",
    },
    {
        "id": "gen-python-loops",
        "category": "programming",
        "topic": "Python Loops (for and while)",
        "keywords": ("python", "loop", "loops", "for", "while", "iteration", "iterate", "range"),
        "summary": "How to write for loops and while loops in Python.",
        "content": (
            "Python provides two primary loop constructs: `for` loops (definite iteration) and `while` loops (indefinite iteration).\n\n"
            "**1. For Loop with `range()`:**\n"
            "```python\n"
            "# Iterate 5 times (0 to 4)\n"
            "for i in range(5):\n"
            '    print(f"Iteration {i}")\n\n'
            "# Iterate over a list\n"
            'fruits = ["apple", "banana", "cherry"]\n'
            "for fruit in fruits:\n"
            "    print(fruit)\n"
            "```\n\n"
            "**2. While Loop:**\n"
            "```python\n"
            "count = 0\n"
            "while count < 3:\n"
            '    print(f"Count: {count}")\n'
            "    count += 1\n"
            "```\n\n"
            "**Control Statements:**\n"
            "- `break`: Terminate the loop immediately.\n"
            "- `continue`: Skip the current iteration and proceed to the next."
        ),
        "source": "Python Documentation (docs.python.org)",
    },
    {
        "id": "gen-python-sorting",
        "category": "programming",
        "topic": "Sorting in Python (sort and sorted)",
        "keywords": ("python", "sort", "sorting", "sorted", "list", "array", "order", "ascending", "descending", "timsort"),
        "summary": "How to sort lists and collections in Python.",
        "content": (
            "Python offers two built-in ways to sort collections:\n\n"
            "1. **`list.sort()`**: Modifies the list in-place and returns `None`.\n"
            "```python\n"
            "nums = [5, 2, 9, 1]\n"
            "nums.sort()\n"
            "print(nums)  # [1, 2, 5, 9]\n"
            "```\n\n"
            "2. **`sorted()`**: Built-in function that returns a new sorted list from any iterable.\n"
            "```python\n"
            "nums = [5, 2, 9, 1]\n"
            "ordered = sorted(nums, reverse=True)\n"
            "print(ordered)  # [9, 5, 2, 1]\n"
            "```\n\n"
            "Both use **Timsort** ($O(n \\log n)$ time complexity)."
        ),
        "source": "Python Standard Library Documentation",
    },
    {
        "id": "gen-binary-search",
        "category": "programming",
        "topic": "Binary Search Algorithm",
        "keywords": ("binary", "search", "algorithm", "sorted", "array", "logarithmic", "time", "complexity", "big o"),
        "summary": "How binary search works with logarithmic time complexity.",
        "content": (
            "Binary Search is an efficient search algorithm that finds the position of a target value within a **sorted array**.\n\n"
            "**Algorithm Steps:**\n"
            "1. Compare the target to the middle element.\n"
            "2. If the target equals the middle element, return its index.\n"
            "3. If the target is smaller, repeat search on the left half.\n"
            "4. If the target is larger, repeat search on the right half.\n\n"
            "**Time Complexity:**\n"
            "- Best Case: $O(1)$ (found at midpoint)\n"
            "- Worst/Average Case: $O(\\log n)$\n"
            "- Space Complexity: $O(1)$ iterative, $O(\\log n)$ recursive."
        ),
        "source": "Introduction to Algorithms (CLRS)",
    },
    {
        "id": "gen-sql-vs-nosql",
        "category": "programming",
        "topic": "SQL vs NoSQL Databases",
        "keywords": ("sql", "nosql", "database", "relational", "mongodb", "postgres", "mysql", "acid"),
        "summary": "Key differences between relational SQL and document NoSQL databases.",
        "content": (
            "**SQL (Relational Databases):**\n"
            "- Examples: PostgreSQL, MySQL, SQLite, Oracle.\n"
            "- Schema: Structured, rigid table schemas with rows and columns.\n"
            "- Querying: Standard SQL with complex joins.\n"
            "- ACID Properties: Strong consistency guarantees.\n\n"
            "**NoSQL (Non-Relational Databases):**\n"
            "- Examples: MongoDB (Document), Redis (Key-Value), Cassandra (Wide-Column), Neo4j (Graph).\n"
            "- Schema: Flexible, dynamic schemas (e.g. JSON/BSON documents).\n"
            "- Scaling: Horizontally scalable across clusters.\n"
            "- Best For: Rapidly evolving data, hierarchical structures, high throughput."
        ),
        "source": "Database System Concepts Reference",
    },
    {
        "id": "gen-rest-apis",
        "category": "programming",
        "topic": "RESTful API Architecture",
        "keywords": ("rest", "api", "http", "get", "post", "put", "delete", "status", "endpoint"),
        "summary": "Principles of Representational State Transfer (REST) APIs.",
        "content": (
            "REST (Representational State Transfer) is an architectural style for networked web services.\n\n"
            "**Core Principles:**\n"
            "- **Statelessness:** Each request from client to server must contain all necessary information.\n"
            "- **Client-Server:** Decoupled frontend and backend systems.\n"
            "- **Uniform Interface:** Standard HTTP methods:\n"
            "  - `GET`: Retrieve resource.\n"
            "  - `POST`: Create resource.\n"
            "  - `PUT` / `PATCH`: Update resource.\n"
            "  - `DELETE`: Remove resource.\n"
            "- **Standard HTTP Status Codes:** `200 OK`, `201 Created`, `400 Bad Request`, `401 Unauthorized`, `404 Not Found`, `500 Internal Error`."
        ),
        "source": "W3C / RFC 9110 HTTP Semantics",
    },

    # --- SCIENCE ---
    {
        "id": "gen-photosynthesis",
        "category": "science",
        "topic": "Photosynthesis",
        "keywords": ("photosynthesis", "plants", "sunlight", "chlorophyll", "glucose", "oxygen", "carbon dioxide"),
        "summary": "Biological process by which plants convert sunlight into chemical energy.",
        "content": (
            "Photosynthesis is the biochemical process by which green plants, algae, and cyanobacteria convert light energy "
            "into chemical energy stored in glucose.\n\n"
            "**Chemical Equation:**\n"
            "$$6\\text{CO}_2 + 6\\text{H}_2\\text{O} + \\text{light energy} \\rightarrow \\text{C}_6\\text{H}_{12}\\text{O}_6 + 6\\text{O}_2$$\n\n"
            "**Stages:**\n"
            "1. **Light-Dependent Reactions:** Occur in the thylakoid membranes of chloroplasts, capturing sunlight to produce ATP and NADPH while releasing oxygen ($O_2$).\n"
            "2. **Light-Independent Reactions (Calvin Cycle):** Occur in the stroma, using ATP and NADPH to fix carbon dioxide ($CO_2$) into carbohydrates (glucose)."
        ),
        "source": "Campbell Biology (12th Edition)",
    },
    {
        "id": "gen-dna-genetics",
        "category": "science",
        "topic": "DNA Structure and Genetics",
        "keywords": ("dna", "genetics", "gene", "chromosome", "nucleotide", "adenine", "thymine", "cytosine", "guanine"),
        "summary": "Structure and function of Deoxyribonucleic Acid (DNA).",
        "content": (
            "DNA (Deoxyribonucleic Acid) is the hereditary molecule that carries genetic instructions in all living organisms.\n\n"
            "**Double Helix Structure:**\n"
            "- Discovered by James Watson, Francis Crick, and Rosalind Franklin.\n"
            "- Composed of two antiparallel strands of alternating sugar (deoxyribose) and phosphate groups.\n"
            "- **Nitrogenous Base Pairs:**\n"
            "  - Adenine (A) pairs strictly with Thymine (T) via 2 hydrogen bonds.\n"
            "  - Guanine (G) pairs strictly with Cytosine (C) via 3 hydrogen bonds.\n"
            "- **Central Dogma of Molecular Biology:** $\\text{DNA} \\xrightarrow{\\text{Transcription}} \\text{RNA} \\xrightarrow{\\text{Translation}} \\text{Protein}$."
        ),
        "source": "Molecular Biology of the Cell",
    },
    {
        "id": "gen-newtons-laws",
        "category": "science",
        "topic": "Newton's Laws of Motion",
        "keywords": ("newton", "laws", "motion", "inertia", "force", "mass", "acceleration", "physics", "gravity"),
        "summary": "Three fundamental classical mechanics laws formulated by Isaac Newton.",
        "content": (
            "Sir Isaac Newton's three laws of motion describe the relationship between a body and the forces acting upon it:\n\n"
            "1. **First Law (Inertia):** An object at rest stays at rest, and an object in motion remains in uniform rectilinear motion "
            "unless acted upon by an external net force.\n"
            "2. **Second Law ($F = ma$):** The rate of change of momentum of a body is directly proportional to the applied force. "
            "$$\\mathbf{F} = m\\mathbf{a}$$\n"
            "3. **Third Law (Action-Reaction):** For every action, there is an equal and opposite reaction ($F_{A \\rightarrow B} = -F_{B \\rightarrow A}$)."
        ),
        "source": "Philosophiae Naturalis Principia Mathematica",
    },
    {
        "id": "gen-thermodynamics",
        "category": "science",
        "topic": "Laws of Thermodynamics",
        "keywords": ("thermodynamics", "energy", "entropy", "heat", "temperature", "conservation", "physics"),
        "summary": "Fundamental physical laws governing heat, energy, and entropy.",
        "content": (
            "The Laws of Thermodynamics define fundamental physical quantities (temperature, energy, entropy) in thermodynamic systems:\n\n"
            "- **Zeroth Law:** If systems A and B are each in thermal equilibrium with C, then A and B are in thermal equilibrium with each other (basis of temperature).\n"
            "- **First Law (Conservation of Energy):** Energy cannot be created or destroyed, only transformed (${\\Delta U = Q - W}$).\n"
            "- **Second Law (Entropy):** The total entropy of an isolated system always increases over time (${\\Delta S \\ge 0}$); heat does not spontaneously flow from cold to hot.\n"
            "- **Third Law:** As temperature approaches absolute zero ($0\\text{ K}$), the entropy of a pure crystalline substance approaches zero."
        ),
        "source": "Feynman Lectures on Physics",
    },
    {
        "id": "gen-solar-system",
        "category": "science",
        "topic": "Solar System and Planets",
        "keywords": ("solar", "system", "planets", "sun", "earth", "mars", "jupiter", "space", "astronomy"),
        "summary": "Structure of our solar system and the eight recognized planets.",
        "content": (
            "Our Solar System consists of our star, the Sun, and everything bound to it by gravity.\n\n"
            "**The Eight Major Planets (in order from the Sun):**\n"
            "1. **Mercury:** Smallest planet, closest to the Sun, heavily cratered.\n"
            "2. **Venus:** Thick carbon dioxide atmosphere, hottest planetary surface.\n"
            "3. **Earth:** Only known planet to harbor liquid surface water and life.\n"
            "4. **Mars:** The 'Red Planet', thin atmosphere, iron oxide surface, contains Olympus Mons.\n"
            "5. **Jupiter:** Largest planet, gas giant with Great Red Spot storm.\n"
            "6. **Saturn:** Gas giant known for its extensive, prominent planetary ring system.\n"
            "7. **Uranus:** Ice giant with an extreme axial tilt (~98 degrees).\n"
            "8. **Neptune:** Most distant major planet, active supersonic wind patterns.\n\n"
            "*Note: Pluto was reclassified as a dwarf planet by the International Astronomical Union (IAU) in 2006.*"
        ),
        "source": "NASA Planetary Fact Sheet",
    },

    # --- MATHEMATICS ---
    {
        "id": "gen-pythagorean-theorem",
        "category": "mathematics",
        "topic": "Pythagorean Theorem",
        "keywords": ("pythagorean", "theorem", "hypotenuse", "triangle", "geometry", "right", "angle", "math"),
        "summary": "Relation between the three sides of a right-angled triangle.",
        "content": (
            "The Pythagorean Theorem is a fundamental principle in Euclidean geometry regarding right-angled triangles:\n\n"
            "$$\\mathbf{a^2 + b^2 = c^2}$$\n\n"
            "- $a$ and $b$ are the lengths of the legs meeting at the right angle ($90^\\circ$).\n"
            "- $c$ is the length of the **hypotenuse** (the longest side opposite the right angle).\n\n"
            "**Example Calculation:**\n"
            "If $a = 3$ and $b = 4$:\n"
            "$$c^2 = 3^2 + 4^2 = 9 + 16 = 25 \\implies c = \\sqrt{25} = 5$$\n"
            "*(3, 4, 5 is a classic Pythagorean triple).*"
        ),
        "source": "Euclid's Elements, Book I",
    },
    {
        "id": "gen-calculus-basics",
        "category": "mathematics",
        "topic": "Basics of Calculus: Derivatives and Integrals",
        "keywords": ("calculus", "derivative", "derivatives", "integral", "integrals", "differentiation", "integration", "math"),
        "summary": "Core concepts of differentiation and integration.",
        "content": (
            "Calculus is the mathematical study of continuous change, divided into two main branches connected by the "
            "**Fundamental Theorem of Calculus**:\n\n"
            "1. **Differential Calculus (Derivatives):**\n"
            "- Measures instantaneous rate of change or the slope of a curve.\n"
            "- Definition: $f'(x) = \\lim_{h \\to 0} \\frac{f(x+h) - f(x)}{h}$\n"
            "- Power Rule: $\\frac{d}{dx}[x^n] = n x^{n-1}$\n\n"
            "2. **Integral Calculus (Integrals):**\n"
            "- Computes accumulation of quantities, such as the area under a curve.\n"
            "- Power Rule for indefinite integration: $\\int x^n dx = \\frac{x^{n+1}}{n+1} + C$ (for $n \\ne -1$)."
        ),
        "source": "Stewart Calculus: Early Transcendentals",
    },
    {
        "id": "gen-prime-numbers",
        "category": "mathematics",
        "topic": "Prime Numbers",
        "keywords": ("prime", "numbers", "divisible", "factors", "math", "cryptography", "factorization"),
        "summary": "Definition and properties of prime numbers.",
        "content": (
            "A **prime number** is a natural number strictly greater than 1 that cannot be formed by multiplying two smaller natural numbers "
            "(i.e., its only positive divisors are 1 and itself).\n\n"
            "**Key Properties:**\n"
            "- **2** is the smallest and only even prime number.\n"
            "- First few primes: $2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, \\dots$\n"
            "- **Fundamental Theorem of Arithmetic:** Every integer greater than 1 either is a prime itself or can be uniquely represented as the product of prime numbers (up to order).\n"
            "- **Application in Cybersecurity:** Large prime numbers form the cryptographic backbone of asymmetric encryption algorithms like RSA."
        ),
        "source": "Number Theory Fundamentals",
    },

    # --- CYBERSECURITY & TECH ---
    {
        "id": "gen-cryptography-basics",
        "category": "cybersecurity",
        "topic": "Symmetric vs Asymmetric Cryptography",
        "keywords": ("cryptography", "encryption", "symmetric", "asymmetric", "aes", "rsa", "public", "private", "key"),
        "summary": "Core distinctions between symmetric key and public key encryption.",
        "content": (
            "**Symmetric Encryption:**\n"
            "- Uses the **same single secret key** for both encryption and decryption.\n"
            "- Examples: AES (Advanced Encryption Standard, 128/256-bit), ChaCha20.\n"
            "- Advantages: Extremely fast, ideal for bulk data encryption (hard drives, TLS session payload).\n\n"
            "**Asymmetric Encryption (Public-Key Cryptography):**\n"
            "- Uses a **mathematically linked key pair**: a Public Key (distributed openly) and a Private Key (kept strictly confidential).\n"
            "- Examples: RSA, ECC (Elliptic Curve Cryptography), Ed25519.\n"
            "- Data encrypted with the public key can only be decrypted by the matching private key.\n"
            "- Used for key exchange (Diffie-Hellman), digital signatures, and identity verification in TLS/HTTPS."
        ),
        "source": "NIST SP 800-175B Cryptographic Standards",
    },
    {
        "id": "gen-zero-trust",
        "category": "cybersecurity",
        "topic": "Zero Trust Security Architecture",
        "keywords": ("zero", "trust", "architecture", "security", "never", "verify", "least", "privilege"),
        "summary": "Core tenet of modern enterprise security: 'Never Trust, Always Verify'.",
        "content": (
            "Zero Trust is a cybersecurity framework requiring all users and devices, whether inside or outside an organization's network, "
            "to be continuously authenticated, authorized, and validated before being granted access.\n\n"
            "**Core Tenets:**\n"
            "1. **Never Trust, Always Verify:** Eliminate implicit trust based on physical location or IP subnet.\n"
            "2. **Least Privilege Access:** Grant users only the minimum necessary permissions required for their role (RBAC/ABAC).\n"
            "3. **Assume Breach:** Design networks assuming attackers already have presence; segment networks micro-architecturally to limit lateral movement.\n"
            "4. **Continuous Telemetry:** Monitor and inspect logs, identity assertions, device health, and network flows in real time."
        ),
        "source": "NIST SP 800-207 Zero Trust Architecture",
    },

    # --- HISTORY & GEOGRAPHY ---
    {
        "id": "gen-world-continents-oceans",
        "category": "geography",
        "topic": "World Continents and Oceans",
        "keywords": ("continents", "oceans", "world", "geography", "earth", "asia", "africa", "pacific", "atlantic"),
        "summary": "The seven continents and five oceans of the world.",
        "content": (
            "**The Seven Continents (by land area):**\n"
            "1. **Asia:** Largest and most populous continent.\n"
            "2. **Africa:** Second largest, home to the Sahara Desert and the Nile River.\n"
            "3. **North America:** Entirely in the Northern Hemisphere.\n"
            "4. **South America:** Home to the Amazon Rainforest and Andes Mountains.\n"
            "5. **Antarctica:** Coldest, driest, and windiest continent, covered in ice sheets.\n"
            "6. **Europe:** Bordered by the Arctic Ocean, Atlantic Ocean, and Mediterranean Sea.\n"
            "7. **Australia (Oceania):** Smallest continental landmass.\n\n"
            "**The Five World Oceans (by size):**\n"
            "1. Pacific Ocean (largest & deepest)\n"
            "2. Atlantic Ocean (second largest)\n"
            "3. Indian Ocean\n"
            "4. Southern (Antarctic) Ocean\n"
            "5. Arctic Ocean (smallest & shallowest)"
        ),
        "source": "National Geographic World Atlas",
    },
    {
        "id": "gen-industrial-revolution",
        "category": "history",
        "topic": "The Industrial Revolution",
        "keywords": ("industrial", "revolution", "steam", "engine", "history", "manufacturing", "factories", "economy"),
        "summary": "Historical transition to modern manufacturing and mechanized industry.",
        "content": (
            "The Industrial Revolution marked the transition from agrarian, handicraft economies to machine-driven "
            "industrial manufacturing, beginning in Great Britain in the mid-18th century (~1760–1840).\n\n"
            "**Major Transformations:**\n"
            "- **Steam Power:** James Watt's improved steam engine provided mechanical power independent of watermills.\n"
            "- **Textile Mechanization:** Spinning Jenny and power looms vastly increased fabric output.\n"
            "- **Iron & Metallurgy:** Transition from charcoal to coke smelting produced stronger structural iron.\n"
            "- **Transportation:** Expansion of railways, canals, and steamships connected global markets.\n"
            "- **Social Impact:** Accelerated urbanization, rise of industrial labor forces, and technological infrastructure."
        ),
        "source": "Cambridge Economic History of Europe",
    },
)


def _tokenize(text: str) -> set[str]:
    """Tokenize query or content into lowercase alphanumeric words of length > 2."""
    return {w.lower() for w in re.findall(r"[a-zA-Z0-9_+#]+", text) if len(w) > 2}


def search_general_knowledge(query: str, limit: int = 3) -> list[dict]:
    """Search general knowledge reference library using multi-keyword and relevance scoring."""
    tokens = _tokenize(query)
    if not tokens:
        return []

    scored_records = []
    for rec in GENERAL_KNOWLEDGE_RECORDS:
        kw_set = {k.lower() for k in rec.get("keywords", ())}
        topic_tokens = _tokenize(rec.get("topic", ""))
        content_tokens = _tokenize(rec.get("content", ""))

        score = 0
        # Keyword exact match bonus
        score += len(tokens & kw_set) * 6
        # Topic title match bonus
        score += len(tokens & topic_tokens) * 5
        # Content overlap
        score += len(tokens & content_tokens) * 1

        if score >= 5:
            scored_records.append((score, rec))

    scored_records.sort(key=lambda x: x[0], reverse=True)
    return [rec for _, rec in scored_records[:limit]]


def synthesize_code_response(query: str) -> str | None:
    """Detect common coding intents and return an accurate, runnable, formatted code solution."""
    lowered = query.lower()

    # Case 1: Add numbers function in Python
    if any(phrase in lowered for phrase in ("add two numbers", "add_numbers", "adds two numbers", "sum of two", "function to add", "function named add")):
        return (
            "Here is a complete, runnable Python function that adds two numbers with type hints and documentation:\n\n"
            "```python\n"
            "def add_numbers(a: float | int, b: float | int) -> float | int:\n"
            '    """Return the sum of two numbers a and b.\n'
            "\n"
            "    Args:\n"
            "        a: The first number.\n"
            "        b: The second number.\n"
            "\n"
            "    Returns:\n"
            "        The arithmetic sum of a and b.\n"
            '    """\n'
            "    return a + b\n"
            "\n"
            "\n"
            "# Example usage:\n"
            "if __name__ == '__main__':\n"
            "    result1 = add_numbers(10, 25)\n"
            '    print(f"10 + 25 = {result1}")\n'
            "\n"
            "    result2 = add_numbers(3.5, 2.5)\n"
            '    print(f"3.5 + 2.5 = {result2}")\n'
            "```\n\n"
            "**Explanation:**\n"
            "- The `+` operator adds the two input values.\n"
            "- Using `float | int` allows the function to handle both integers and decimal floating-point numbers seamlessly."
        )

    # Case 2: Reverse a string
    if any(phrase in lowered for phrase in ("reverse a string", "reverse string", "reverse_string", "reversing a string")):
        return (
            "Here is an idiomatic Python function to reverse a string:\n\n"
            "```python\n"
            "def reverse_string(text: str) -> str:\n"
            '    """Return the reversed version of the input string using slice notation."""\n'
            "    return text[::-1]\n"
            "\n"
            "\n"
            "# Example usage:\n"
            'sample = "Hello World"\n'
            "print(reverse_string(sample))  # Output: dlroW olleH\n"
            "```\n\n"
            "**Explanation:**\n"
            "- `[::-1]` uses Python's extended slice syntax with a step of `-1`, which steps backwards through the string efficiently."
        )

    # Case 3: Prime check
    if any(phrase in lowered for phrase in ("check prime", "is_prime", "is prime", "prime number function", "prime check")):
        return (
            "Here is an optimized Python function to check whether a given integer is a prime number:\n\n"
            "```python\n"
            "import math\n"
            "\n"
            "def is_prime(n: int) -> bool:\n"
            '    """Determine if a positive integer n is a prime number."""\n'
            "    if n <= 1:\n"
            "        return False\n"
            "    if n <= 3:\n"
            "        return True\n"
            "    if n % 2 == 0 or n % 3 == 0:\n"
            "        return False\n"
            "\n"
            "    # Check divisors up to sqrt(n) with 6k +/- 1 optimization\n"
            "    i = 5\n"
            "    while i * i <= n:\n"
            "        if n % i == 0 or n % (i + 2) == 0:\n"
            "            return False\n"
            "        i += 6\n"
            "    return True\n"
            "\n"
            "\n"
            "# Example usage:\n"
            "for num in [2, 7, 10, 29, 49]:\n"
            '    print(f"{num} is prime: {is_prime(num)}")\n'
            "```"
        )

    # Case 4: Loops in Python
    if any(phrase in lowered for phrase in ("loop in python", "python loop", "write a loop", "for loop", "while loop", "how to loop", "loops in python")):
        return (
            "Here is how to write loops in Python using `for` and `while` constructs:\n\n"
            "```python\n"
            "# 1. For loop over a range of numbers\n"
            "for i in range(5):\n"
            '    print(f"Iteration: {i}")\n\n'
            "# 2. For loop over a collection\n"
            'items = ["cybersecurity", "digital forensics", "threat intelligence"]\n'
            "for item in items:\n"
            '    print(f"Service: {item}")\n\n'
            "# 3. While loop with condition\n"
            "count = 0\n"
            "while count < 3:\n"
            '    print(f"Count: {count}")\n'
            "    count += 1\n"
            "```\n\n"
            "**Key Concepts:**\n"
            "- Use `for item in iterable:` for iterating over lists, tuples, or ranges.\n"
            "- Use `while condition:` to repeat execution as long as a boolean expression is True.\n"
            "- `break` exits the loop early, while `continue` skips to the next iteration."
        )

    # Case 5: Sort a list in Python
    if any(phrase in lowered for phrase in ("sort a list", "sort list", "sorting in python", "how to sort", "sorted list", "sort an array", "sort array")):
        return (
            "Here is how to sort a list in Python using `.sort()` and `sorted()`:\n\n"
            "```python\n"
            "# 1. In-place sort using list.sort()\n"
            "numbers = [42, 12, 88, 3, 27]\n"
            "numbers.sort()\n"
            'print(f"Sorted in-place: {numbers}")  # Output: [3, 12, 27, 42, 88]\n\n'
            "# 2. Returning a new sorted list using sorted()\n"
            'words = ["cybersecurity", "forensics", "analytics", "governance"]\n'
            "ordered = sorted(words)\n"
            'print(f"Sorted new list: {ordered}")\n\n'
            "# 3. Custom key and reverse sorting\n"
            "descending = sorted(numbers, reverse=True)\n"
            'print(f"Descending: {descending}")  # Output: [88, 42, 27, 12, 3]\n'
            "```\n\n"
            "**Key Differences:**\n"
            "- `list.sort()` sorts the original list in-place and returns `None`.\n"
            "- `sorted(iterable)` returns a brand-new sorted list, preserving the original sequence.\n"
            "- Both use Python's Timsort algorithm with $O(n \\log n)$ worst-case time complexity."
        )

    return None
