"""Official verified knowledge records for Black Intel Private Limited (The Black Intelligence).

Sourced directly from https://theblackintel.com/ (About, Services, Contact, Leadership, Unit 717).
All records are tenant-scoped, published, and contain official source URLs.
"""

from bson import ObjectId

OFFICIAL_BLACK_INTEL_KNOWLEDGE = (
    {
        "official_key": "company-overview",
        "title": "Black Intel Company Overview",
        "content": (
            "Black Intel Private Limited (also known as The Black Intelligence) is a sovereign digital power "
            "unit operating at the intersection of advanced cybersecurity, digital forensics, threat intelligence, "
            "and intelligence-driven defense. The company was founded to address the critical gap between conventional "
            "cybersecurity and modern cyber threats, delivering defensive, investigative, and strategic advisory operations "
            "strictly within applicable national and international legal frameworks."
        ),
        "source_url": "https://theblackintel.com/about/company-overview",
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
    },
    {
        "official_key": "core-services-overview",
        "title": "What services does Black Intel offer?",
        "content": (
            "Black Intel provides comprehensive cybersecurity, digital forensics, and intelligence capabilities across "
            "multiple specialized divisions: Cybercrime & Digital Investigations, Computer Forensics, Mobile Investigations, "
            "Cloud & Gmail Cloud Investigations, OSINT (Open-Source Intelligence), and Defensive Security Architecture."
        ),
        "source_url": "https://theblackintel.com/",
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
    },
    {
        "official_key": "service-computer-forensics",
        "title": "Computer Forensics and Evidence Analysis",
        "content": (
            "Black Intel's Computer Forensics service provides forensic disk imaging, volatile memory analysis, deleted "
            "data recovery, log reconstruction, and malware artifact examination under strict evidentiary integrity standards "
            "suitable for corporate and legal proceedings."
        ),
        "source_url": "https://theblackintel.com/services/computer-forensics",
    },
    {
        "official_key": "service-mobile-investigations",
        "title": "Mobile Device Investigations",
        "content": (
            "Black Intel's Mobile Investigations division conducts forensic acquisition, encrypted artifact recovery, "
            "communication extraction, location artifact analysis, and application sandbox investigation across iOS and Android devices."
        ),
        "source_url": "https://theblackintel.com/services/mobile-investigations",
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
    },
    {
        "official_key": "intended-clients",
        "title": "Who does Black Intel work with?",
        "content": (
            "Black Intel serves enterprises, institutions, governments, and legal or investigative professionals requiring "
            "high-assurance cybersecurity defense, confidential digital forensics, incident reconstruction, or strategic threat intelligence."
        ),
        "source_url": "https://theblackintel.com/about/company-overview",
    },
    {
        "official_key": "client-engagement-process",
        "title": "How does Black Intel work with clients?",
        "content": (
            "Black Intel operates through a confidential consultation and scoping process. Because security and investigative "
            "requirements vary, prospective clients request a consultation to confirm technical scope. All engagements are strictly "
            "compartmentalized, legally compliant, and advisory in nature."
        ),
        "source_url": "https://theblackintel.com/contact",
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
    },
    {
        "official_key": "leadership-structure",
        "title": "Black Intel Leadership",
        "content": (
            "Black Intel Private Limited's leadership structure includes Director Aryan Kumar (also publicly known as Aryan Bharti) "
            "along with core leadership members Abhishek Kumar, Gaurav Saini, Maini Saini, and Shahbaz Hussain across executive management "
            "and intelligence operations."
        ),
        "source_url": "https://theblackintel.com/about/leadership",
    },
    {
        "official_key": "legal-service-scope",
        "title": "Black Intel Service Scope and Boundaries",
        "content": (
            "Black Intel states that all cybersecurity, digital forensics, and intelligence analysis services operate strictly "
            "within applicable national and international laws and are defensive, investigative, and advisory in nature."
        ),
        "source_url": "https://theblackintel.com/",
    },
)


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
