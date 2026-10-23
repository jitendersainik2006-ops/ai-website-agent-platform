"""Official verified knowledge records for Black Intel Private Limited (The Black Intelligence).

Sourced directly from official company records and https://theblackintel.com/
(About, Services, Contact, Leadership, Divisions, and Policies).
All records are tenant-scoped, verified, published, and contain official source URLs.
Includes a scalable chunking engine supporting dynamic scaling for large libraries.
"""

from bson import ObjectId
import hashlib
import re

OFFICIAL_BLACK_INTEL_KNOWLEDGE = (
    {
        "official_key": "company-overview",
        "title": "Black Intel Company Overview",
        "content": (
            "Black Intel Private Limited (also known as The Black Intelligence) is a sovereign digital power "
            "unit operating at the intersection of advanced cybersecurity, digital forensics, threat intelligence, "
            "and intelligence-driven defense. The company was founded to address the critical gap between conventional "
            "cybersecurity and modern digital threats, delivering defensive, investigative, and strategic advisory operations "
            "strictly within applicable national and international legal frameworks."
        ),
        "source_url": "https://theblackintel.com/about/company-overview",
        "source_title": "Company Overview | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "vision-mission",
        "title": "Black Intel Vision and Mission",
        "content": (
            "Black Intel's mission is to build the world's most powerful hybrid intelligence brand where cybersecurity, "
            "artificial intelligence, digital forensics, and counter-intelligence merge into a new era of digital order. "
            "The company operates under three core tenets: absolute precision in investigation, unwavering commitment "
            "to protection, and strategic dominance in the digital domain."
        ),
        "source_url": "https://theblackintel.com/about/vision-mission",
        "source_title": "Vision & Mission | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "organizational-structure",
        "title": "Black Intel Organizational Structure",
        "content": (
            "Black Intel Private Limited's organizational structure is modeled after elite intelligence agencies, "
            "ensuring operational efficiency, compartmentalized security, and rapid response capabilities. Each division "
            "operates with autonomous authority while maintaining strategic alignment with the core mission. This hybrid "
            "structure combines military-grade rigor with private-sector agility across specialized units."
        ),
        "source_url": "https://theblackintel.com/about/company-overview",
        "source_title": "Organizational Architecture | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "core-services-overview",
        "title": "What services does Black Intel offer?",
        "content": (
            "Black Intel provides comprehensive cybersecurity, digital forensics, and threat intelligence capabilities across "
            "specialized divisions: Cyber Offense Command (proactive threat neutralization and penetration testing), "
            "Cybercrime & Digital Investigations, Computer Forensics, Mobile Investigations, Cloud & Gmail Cloud Investigations, "
            "OSINT (Open-Source Intelligence), and Defensive Security Division (resilient architecture and SOC operations)."
        ),
        "source_url": "https://theblackintel.com/",
        "source_title": "Services Overview | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "service-cyber-offense",
        "title": "Cyber Offense Command & Penetration Testing",
        "content": (
            "Black Intel's Cyber Offense Command focuses on proactive threat neutralization, penetration operations, red teaming, "
            "and zero-day hunting. Our red teams emulate nation-state actors and advanced persistent threats (APT simulation) "
            "to rigorously test and validate defensive postures before adversaries exploit vulnerabilities."
        ),
        "source_url": "https://theblackintel.com/services/cyber-offense",
        "source_title": "Cyber Offense Command | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "service-defensive-security",
        "title": "Defensive Security Division & SOC Operations",
        "content": (
            "The Defensive Security Division builds resilient digital defense architectures, operates SIEM & SOC (Security Operations Center) "
            "monitoring, provides continuous threat detection, and deploys intelligence-grade defenses across enterprise cloud and network environments."
        ),
        "source_url": "https://theblackintel.com/services/defensive-security",
        "source_title": "Defensive Security Division | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "service-cybercrime-investigation",
        "title": "Cybercrime and Digital Investigations Service",
        "content": (
            "Black Intel's Cybercrime & Digital Investigation Division specializes in advanced digital trace analysis, "
            "financial fraud detection, breach attribution, structured incident reconstruction, and countermeasure "
            "engineering. All investigations maintain strict chain of custody, legal adherence, and absolute client discretion."
        ),
        "source_url": "https://theblackintel.com/services/cybercrime-investigation",
        "source_title": "Cybercrime Investigations | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "service-computer-forensics",
        "title": "Computer Forensics and Evidence Analysis",
        "content": (
            "Black Intel's Computer Forensics service delivers forensic disk imaging, volatile memory (RAM) analysis, deleted "
            "data recovery, log reconstruction, and malware artifact examination under strict evidentiary integrity standards "
            "suitable for corporate, investigative, and legal proceedings."
        ),
        "source_url": "https://theblackintel.com/services/computer-forensics",
        "source_title": "Computer Forensics Lab | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "service-forensic-truth-extraction",
        "title": "Forensic Truth Extraction & Recovery",
        "content": (
            "The Digital Forensics Unit specializes in 'Forensic Truth Extraction' — decoding truth from digital chaos. "
            "Capabilities include physical image acquisition, deep & dark web tracking, geo-forensics and movement pattern reconstruction, "
            "and recovery of critical evidence from the most sophisticated compromises."
        ),
        "source_url": "https://theblackintel.com/services/computer-forensics",
        "source_title": "Truth Extraction & Forensics | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "service-mobile-investigations",
        "title": "Mobile Device Investigations",
        "content": (
            "Black Intel's Mobile Investigations division conducts forensic acquisition, encrypted artifact recovery, "
            "communication extraction, location artifact analysis, and application sandbox investigation across iOS and Android devices."
        ),
        "source_url": "https://theblackintel.com/services/mobile-investigations",
        "source_title": "Mobile Investigations | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "service-cloud-investigations",
        "title": "Cloud and Gmail Cloud Investigations",
        "content": (
            "Black Intel's Cloud Investigations capability examines multi-cloud infrastructure, SaaS platforms, and "
            "Gmail/Google Workspace environments. It focuses on access log reconstruction, unauthorized mailbox delegation, "
            "OAuth token abuse, and data exfiltration analysis."
        ),
        "source_url": "https://theblackintel.com/services/cloud-investigations",
        "source_title": "Cloud Investigations | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "service-osint",
        "title": "OSINT and Threat Intelligence",
        "content": (
            "Black Intel's OSINT (Open-Source Intelligence) division performs deep intelligence collection, digital footprint "
            "profiling, metadata analysis, dark web monitoring, and structured public data correlation to anticipate threats "
            "through global intelligence networks."
        ),
        "source_url": "https://theblackintel.com/services/osint",
        "source_title": "OSINT Intelligence | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "intended-clients",
        "title": "Who does Black Intel work with?",
        "content": (
            "Black Intel serves enterprises, institutions, governments, and legal or investigative professionals requiring "
            "high-assurance cybersecurity defense, confidential digital forensics, incident reconstruction, or strategic threat intelligence."
        ),
        "source_url": "https://theblackintel.com/about/company-overview",
        "source_title": "Client Scope | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "leadership-structure",
        "title": "Black Intel Leadership & Directors",
        "content": (
            "Black Intel Private Limited's leadership structure is led by Director Aryan Kumar (also publicly known as Aryan Bharti "
            "or Aryan Kumar Bharti), providing organizational leadership and strategic direction. Core leadership includes "
            "Director Maini Saini, General Manager Abhishek Kumar (operational management and coordination), Shahbaz Hussain "
            "(Intelligence Cell Core Member), and Gaurav Saini (Legal Advisor & Chartered Accountant)."
        ),
        "source_url": "https://theblackintel.com/about/leadership",
        "source_title": "Leadership | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "client-engagement-process",
        "title": "How does Black Intel work with clients?",
        "content": (
            "Black Intel operates through a confidential consultation and technical scoping process. Prospective clients request "
            "a consultation to confirm operational scope and technical requirements. All engagements are strictly compartmentalized, "
            "legally compliant, and advisory in nature."
        ),
        "source_url": "https://theblackintel.com/contact",
        "source_title": "Client Engagement | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "official-contact-details",
        "title": "Black Intel Official Contact Details",
        "content": (
            "Official inquiries and consultation requests for Black Intel Private Limited can be submitted via the contact page "
            "at https://theblackintel.com/contact, via email at abhishek.managerr@gmail.com, by phone at +91 9205105369, "
            "or via WhatsApp at https://wa.me/919205105369."
        ),
        "source_url": "https://theblackintel.com/contact",
        "source_title": "Contact | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "pricing-policy",
        "title": "Black Intel Service Pricing",
        "content": (
            "Black Intel does not publish fixed public price lists, as cybersecurity operations and digital forensics engagements "
            "are scoped individually based on operational complexity, infrastructure scale, and urgency. Clients should request a "
            "consultation or contact the team directly for formal proposals."
        ),
        "source_url": "https://theblackintel.com/contact",
        "source_title": "Pricing Policy | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "appointment-booking-instructions",
        "title": "How to Book an Appointment or Consultation",
        "content": (
            "To schedule a consultation with Black Intel, visitors and clients should use the appointment booking form on the platform. "
            "Select an available date and verified time slot, enter your details, and submit the confirmation. The chat assistant cannot "
            "directly reserve or modify appointment times."
        ),
        "source_url": "https://theblackintel.com/contact",
        "source_title": "Appointment Booking | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "legal-service-scope",
        "title": "Black Intel Service Scope and Boundaries",
        "content": (
            "Black Intel states that all cybersecurity, digital forensics, and intelligence analysis services operate strictly "
            "within applicable national and international laws and are defensive, investigative, and advisory in nature."
        ),
        "source_url": "https://theblackintel.com/",
        "source_title": "Legal Scope | The Black Intelligence",
        "verified": True,
    },
    {
        "official_key": "confidentiality-nda",
        "title": "Confidentiality and Non-Disclosure Commitment",
        "content": (
            "Black Intel operates under the highest standards of operational security and client confidentiality. All client "
            "investigations, forensic evidence, and intelligence consultations are protected under strict non-disclosure agreements (NDAs) "
            "and compartmentalized access controls."
        ),
        "source_url": "https://theblackintel.com/about/company-overview",
        "source_title": "Confidentiality & NDA | The Black Intelligence",
        "verified": True,
    },
)


def normalize_text(text: str) -> str:
    """Normalize whitespace and strip extraneous control characters."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_document(
    title: str,
    text: str,
    source_url: str = "https://theblackintel.com/",
    chunk_size: int = 400,
    overlap: int = 60,
) -> list[dict]:
    """Divide a long document into meaningful, searchable chunks without arbitrary hard limits.

    Supports scaling knowledge libraries to 10,000+ entries dynamically.
    """
    clean = normalize_text(text)
    if not clean:
        return []

    words = clean.split(" ")
    if len(words) <= chunk_size:
        return [{
            "title": title,
            "content": clean,
            "source_url": source_url,
            "chunk_index": 0,
            "hash": hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16],
        }]

    chunks = []
    start = 0
    idx = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_words = words[start:end]
        chunk_text = " ".join(chunk_words)
        chunks.append({
            "title": f"{title} (Part {idx + 1})",
            "content": chunk_text,
            "source_url": source_url,
            "chunk_index": idx,
            "hash": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:16],
        })
        idx += 1
        if end >= len(words):
            break
        start += max(1, chunk_size - overlap)

    return chunks


def sync_official_knowledge(db, tenant_id: str | ObjectId) -> int:
    """Idempotently sync published official Black Intel knowledge for a tenant."""
    tenant_oid = ObjectId(tenant_id) if isinstance(tenant_id, str) else tenant_id
    updated_count = 0
    for record in OFFICIAL_BLACK_INTEL_KNOWLEDGE:
        db.knowledge.update_one(
            {"tenant_id": tenant_oid, "official_key": record["official_key"]},
            {"$set": {"tenant_id": tenant_oid, **record, "status": "published"}},
            upsert=True,
        )
        updated_count += 1
    return updated_count
