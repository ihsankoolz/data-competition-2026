"""Curated names: real public hospitals, invented cross-border groups and the demo anchors.

Real hospital names are used for realism (the brief itself names National University
Hospital). Every ID, contact, transaction and amount generated for them is fictional.
"""

from __future__ import annotations

from .names import NameSpec, make_spec

# Demo anchor keys (tests and the demo script refer to these)
NUH, RSCM, SIRIRAJ, HKL, CHORAY, BIOMED = "NUH", "RSCM", "SIRIRAJ", "HKL", "CHORAY", "BIOMED"
CHORAY_MST = "0301234567"

GROUPS = {
    "GRP01": "Sentosa Healthcare Group",
    "GRP02": "Merlion Diagnostics Group",
    "GRP03": "Andaman Medical Group",
    "GRP04": "Mekong Health Partners",
    "GRP05": "Garuda Lab Network",
    "GRP06": "Straits Clinical Group",
}


def _sg_public(local: str, acr: str, legal: str | None = None) -> NameSpec:
    return make_spec(
        "SG",
        "public_hospital",
        local,
        legal=legal or f"{local} Pte Ltd",
        city="Singapore",
        acronyms=(acr,) if acr else (),
    )


def _my_public(local: str, english: str, city: str, acr: str = "", **kw) -> NameSpec:
    return make_spec(
        "MY",
        "public_hospital",
        local,
        english,
        city=city,
        acronyms=(acr,) if acr else (),
        lang_alts=(english,),
        **kw,
    )


_ID_PREFIX = {
    "RSUPN": "Rumah Sakit Umum Pusat Nasional",
    "RSUP": "Rumah Sakit Umum Pusat",
    "RSUD": "Rumah Sakit Umum Daerah",
    "RSPAD": "Rumah Sakit Pusat Angkatan Darat",
    "RS": "Rumah Sakit",
}


def _id_public(local: str, city: str, acr: str = "", **kw) -> NameSpec:
    prefix, core = local.split(" ", 1)
    long = f"{_ID_PREFIX[prefix]} {core}"
    english = f"{core} Hospital" if prefix in ("RS", "RSPAD") else f"{core} General Hospital"
    alts = tuple(kw.pop("lang_alts", ())) or (long, english)
    return make_spec(
        "ID",
        "public_hospital",
        local,
        english,
        legal=long,
        city=city,
        acronyms=(acr,) if acr else (),
        lang_alts=alts,
        **kw,
    )


def _vn(seg: str, local: str, english: str, city: str, **kw) -> NameSpec:
    alts = tuple(kw.pop("lang_alts", ())) or (english,)
    return make_spec("VN", seg, local, english, city=city, lang_alts=alts, **kw)


def _th(seg: str, local: str, english: str, city: str, **kw) -> NameSpec:
    return make_spec(
        "TH",
        seg,
        local,
        english,
        legal=local,
        legal_rom=english,
        city=city,
        lang_alts=(english,),
        **kw,
    )


def curated_specs() -> list[NameSpec]:
    """Fixed specs, in a fixed order. Segment slots are filled with these before templates."""
    s: list[NameSpec] = []

    # ---------------- Singapore ----------------
    s.append(
        make_spec(
            "SG",
            "public_hospital",
            "National University Hospital",
            legal="National University Hospital (S) Pte Ltd",
            city="Singapore",
            acronyms=("NUH",),
            key=NUH,
            forced_card_name="National University Hospital (S) Pte Ltd",
        )
    )
    for local, acr in [
        ("Tan Tock Seng Hospital", "TTSH"),
        ("KK Women's and Children's Hospital", "KKH"),
        ("Singapore General Hospital", "SGH"),
        ("Changi General Hospital", "CGH"),
        ("Khoo Teck Puat Hospital", "KTPH"),
        ("Ng Teng Fong General Hospital", "NTFGH"),
        ("Sengkang General Hospital", "SKH"),
        ("Alexandra Hospital", "AH"),
        ("Woodlands Hospital", ""),
        ("Institute of Mental Health", "IMH"),
        ("National Cancer Centre Singapore", "NCCS"),
        ("National Heart Centre Singapore", "NHCS"),
        ("National Skin Centre", "NSC"),
        ("Jurong Community Hospital", "JCH"),
    ]:
        s.append(_sg_public(local, acr))
    for local in ["Mount Serene Hospital", "Mount Serene Novena Hospital"]:
        s.append(
            make_spec(
                "SG",
                "private_hospital",
                local,
                legal=f"{local} Pte Ltd",
                city="Singapore",
                pair_key="PAIR01",
            )
        )
    for local in [
        "Kingsmead Hospital",
        "Rivervale Medical Centre",
        "Tanjong Park Hospital",
        "Eastpoint Hospital",
    ]:
        s.append(
            make_spec("SG", "private_hospital", local, legal=f"{local} Pte Ltd", city="Singapore")
        )
    s.append(
        make_spec(
            "SG",
            "private_hospital",
            "Sentosa Specialist Hospital",
            legal="Sentosa Specialist Hospital Pte Ltd",
            city="Singapore",
            group_id="GRP01",
        )
    )
    s.append(
        make_spec(
            "SG",
            "laboratory",
            "Merlion Diagnostics",
            legal="Merlion Diagnostics Pte Ltd",
            city="Singapore",
            group_id="GRP02",
        )
    )
    s.append(
        make_spec(
            "SG",
            "laboratory",
            "Garuda Lab Singapore",
            legal="Garuda Lab Singapore Pte Ltd",
            city="Singapore",
            group_id="GRP05",
        )
    )
    s.append(
        make_spec(
            "SG",
            "laboratory",
            "Straits Clinical Laboratories",
            legal="Straits Clinical Laboratories Pte Ltd",
            city="Singapore",
            group_id="GRP06",
        )
    )
    for site in ["Bedok", "Tampines"]:
        s.append(
            make_spec(
                "SG",
                "clinic",
                f"Orchid Family Clinic {site}",
                legal=f"Orchid Family Clinic ({site}) Pte Ltd",
                city="Singapore",
                pair_key="PAIR02",
            )
        )
    s.append(
        make_spec(
            "SG",
            "distributor",
            "BioMed Lab Supplies",
            legal="BioMed Lab Supplies Pte Ltd",
            city="Singapore",
            key=BIOMED,
            forced_card_name="BioMed Lab Supplies Pte Ltd",
        )
    )

    # ---------------- Malaysia ----------------
    s.append(
        _my_public(
            "Hospital Kuala Lumpur",
            "Kuala Lumpur Hospital",
            "Kuala Lumpur",
            "HKL",
            key=HKL,
            forced_card_name="Hospital Kuala Lumpur",
        )
    )
    for local, english, city, acr in [
        ("Hospital Pulau Pinang", "Penang General Hospital", "Georgetown", "HPP"),
        ("Hospital Sultanah Aminah", "Sultanah Aminah Hospital", "Johor Bahru", "HSA"),
        ("Hospital Umum Sarawak", "Sarawak General Hospital", "Kuching", "HUS"),
        ("Hospital Queen Elizabeth", "Queen Elizabeth Hospital", "Kota Kinabalu", "HQE"),
        ("Hospital Tengku Ampuan Rahimah", "Tengku Ampuan Rahimah Hospital", "Klang", "HTAR"),
        ("Hospital Raja Permaisuri Bainun", "Raja Permaisuri Bainun Hospital", "Ipoh", "HRPB"),
        ("Hospital Sultanah Bahiyah", "Sultanah Bahiyah Hospital", "Alor Setar", "HSB"),
        ("Hospital Selayang", "Selayang Hospital", "Selayang", ""),
        ("Hospital Serdang", "Serdang Hospital", "Kajang", ""),
        ("Hospital Sungai Buloh", "Sungai Buloh Hospital", "Sungai Buloh", ""),
        ("Hospital Putrajaya", "Putrajaya Hospital", "Putrajaya", ""),
        ("Hospital Melaka", "Melaka General Hospital", "Melaka", ""),
        ("Hospital Tuanku Ja'afar", "Tuanku Ja'afar Hospital", "Seremban", "HTJ"),
        (
            "Hospital Raja Perempuan Zainab II",
            "Raja Perempuan Zainab II Hospital",
            "Kota Bharu",
            "HRPZ II",
        ),
        ("Hospital Tengku Ampuan Afzan", "Tengku Ampuan Afzan Hospital", "Kuantan", "HTAA"),
        (
            "Hospital Canselor Tuanku Muhriz",
            "Chancellor Tuanku Muhriz Hospital",
            "Kuala Lumpur",
            "HCTM",
        ),
        (
            "Pusat Perubatan Universiti Malaya",
            "University Malaya Medical Centre",
            "Kuala Lumpur",
            "UMMC",
        ),
    ]:
        s.append(_my_public(local, english, city, acr))
    for local, city, pair in [
        ("Seroja Hospital Kuala Lumpur", "Kuala Lumpur", "PAIR03"),
        ("Seroja Hospital Ampang", "Ampang", "PAIR03"),
        ("Anggerik Bandar Utama Specialist Hospital", "Petaling Jaya", "PAIR04"),
        ("Anggerik Ampang Specialist Hospital", "Ampang", "PAIR04"),
        ("Damansara Jaya Medical Centre Cheras", "Cheras", "PAIR05"),
        ("Damansara Jaya Medical Centre Petaling Jaya", "Petaling Jaya", "PAIR05"),
    ]:
        s.append(
            make_spec(
                "MY", "private_hospital", local, legal=f"{local} Sdn Bhd", city=city, pair_key=pair
            )
        )
    s.append(
        make_spec(
            "MY",
            "private_hospital",
            "Sentosa Specialist Hospital Kuala Lumpur",
            legal="Sentosa Specialist Hospital Kuala Lumpur Sdn Bhd",
            city="Kuala Lumpur",
            group_id="GRP01",
        )
    )
    s.append(
        make_spec(
            "MY",
            "private_hospital",
            "Andaman Medical Centre Penang",
            legal="Andaman Medical Centre Penang Sdn Bhd",
            city="Georgetown",
            group_id="GRP03",
        )
    )
    s.append(
        make_spec(
            "MY",
            "laboratory",
            "Garuda Lab Malaysia",
            legal="Garuda Lab (M) Sdn Bhd",
            city="Kuala Lumpur",
            group_id="GRP05",
        )
    )
    s.append(
        make_spec(
            "MY",
            "laboratory",
            "Straits Clinical Laboratories Johor",
            legal="Straits Clinical Laboratories (M) Sdn Bhd",
            city="Johor Bahru",
            group_id="GRP06",
        )
    )

    # ---------------- Indonesia ----------------
    s.append(
        _id_public(
            "RS Cipto Mangunkusumo",
            "Jakarta",
            "RSCM",
            key=RSCM,
            forced_card_name="RS Cipto Mangunkusumo",
            lang_alts=("Rumah Sakit Cipto Mangunkusumo", "RSCM", "Cipto Mangunkusumo Hospital"),
        )
    )
    for local, city, acr in [
        ("RSUP Dr. Sardjito", "Yogyakarta", ""),
        ("RSUD Dr. Soetomo", "Surabaya", ""),
        ("RSUP Dr. Hasan Sadikin", "Bandung", "RSHS"),
        ("RSUP Fatmawati", "Jakarta", ""),
        ("RSUP Persahabatan", "Jakarta", ""),
        ("RSPAD Gatot Soebroto", "Jakarta", "RSPAD"),
        ("RSUP Dr. Kariadi", "Semarang", ""),
        ("RSUP H. Adam Malik", "Medan", "RSHAM"),
        ("RSUP Prof. Dr. I.G.N.G. Ngoerah", "Denpasar", ""),
        ("RSUP Dr. Wahidin Sudirohusodo", "Makassar", ""),
        ("RSUD Tarakan", "Jakarta", ""),
        ("RSUP Dr. M. Djamil", "Padang", ""),
        ("RSUD Dr. Moewardi", "Surakarta", ""),
        ("RS Kanker Dharmais", "Jakarta", ""),
        ("RS Jantung Harapan Kita", "Jakarta", ""),
        ("RSUP Dr. Mohammad Hoesin", "Palembang", "RSMH"),
        ("RSUD Dr. Saiful Anwar", "Malang", "RSSA"),
        ("RSUD Pasar Minggu", "Jakarta", ""),
        ("RSUP Dr. Sitanala", "Tangerang", ""),
    ]:
        s.append(_id_public(local, city, acr))
    for local, city, pair in [
        ("Cendrawasih Kebon Jeruk", "Jakarta", "PAIR06"),
        ("Cendrawasih Karawaci", "Tangerang", "PAIR06"),
        ("Nusa Keluarga Kelapa Gading", "Jakarta", "PAIR07"),
        ("Nusa Keluarga Bekasi", "Bekasi", "PAIR07"),
        ("Puri Kencana Jatinegara", "Jakarta", "PAIR08"),
        ("Puri Kencana Depok", "Depok", "PAIR08"),
    ]:
        s.append(
            make_spec(
                "ID",
                "private_hospital",
                f"RS {local}",
                f"{local} Hospital",
                legal=f"PT Rumah Sakit {local}",
                city=city,
                pair_key=pair,
                lang_alts=(f"Rumah Sakit {local}", f"{local} Hospital"),
            )
        )
    s.append(
        make_spec(
            "ID",
            "private_hospital",
            "RS Sentosa Specialist Jakarta",
            "Sentosa Specialist Hospital Jakarta",
            legal="PT Sentosa Specialist Hospital Indonesia",
            city="Jakarta",
            group_id="GRP01",
            lang_alts=(
                "Rumah Sakit Sentosa Specialist Jakarta",
                "Sentosa Specialist Hospital Jakarta",
            ),
        )
    )
    s.append(
        make_spec(
            "ID",
            "laboratory",
            "Laboratorium Garuda Medika",
            "Garuda Medika Laboratory",
            legal="PT Laboratorium Garuda Medika",
            city="Jakarta",
            group_id="GRP05",
            lang_alts=("Garuda Medika Laboratory",),
        )
    )

    # ---------------- Vietnam ----------------
    s.append(
        _vn(
            "public_hospital",
            "Bệnh viện Chợ Rẫy",
            "Cho Ray Hospital",
            "Ho Chi Minh City",
            key=CHORAY,
            forced_card_name="Bệnh viện Chợ Rẫy",
        )
    )
    for local, english, city in [
        ("Bệnh viện Bạch Mai", "Bach Mai Hospital", "Hanoi"),
        ("Bệnh viện Hữu nghị Việt Đức", "Viet Duc University Hospital", "Hanoi"),
        ("Bệnh viện Trung ương Huế", "Hue Central Hospital", "Hue"),
        ("Bệnh viện Từ Dũ", "Tu Du Hospital", "Ho Chi Minh City"),
        ("Bệnh viện Nhân dân 115", "People's Hospital 115", "Ho Chi Minh City"),
        ("Bệnh viện Thống Nhất", "Thong Nhat Hospital", "Ho Chi Minh City"),
        ("Bệnh viện Đà Nẵng", "Da Nang Hospital", "Da Nang"),
        ("Bệnh viện K", "K Hospital", "Hanoi"),
        ("Bệnh viện Nhi Trung ương", "National Children's Hospital", "Hanoi"),
        ("Bệnh viện Phụ sản Hà Nội", "Hanoi Obstetrics and Gynecology Hospital", "Hanoi"),
        ("Bệnh viện Nhân dân Gia Định", "Gia Dinh People's Hospital", "Ho Chi Minh City"),
        ("Bệnh viện Đại học Y Dược TP.HCM", "University Medical Center HCMC", "Ho Chi Minh City"),
        ("Bệnh viện Bệnh Nhiệt đới Trung ương", "National Hospital for Tropical Diseases", "Hanoi"),
        ("Bệnh viện Hùng Vương", "Hung Vuong Hospital", "Ho Chi Minh City"),
        ("Bệnh viện Xanh Pôn", "Saint Paul Hospital", "Hanoi"),
        ("Bệnh viện Đa khoa Trung ương Cần Thơ", "Can Tho Central General Hospital", "Can Tho"),
    ]:
        s.append(_vn("public_hospital", local, english, city))
    for n in ("1", "2"):
        s.append(
            _vn(
                "public_hospital",
                f"Bệnh viện Nhi Đồng {n}",
                f"Children's Hospital {n}",
                "Ho Chi Minh City",
                pair_key="PAIR11",
            )
        )
    for local, english, city, pair in [
        ("Bệnh viện Ngọc Lan Sài Gòn", "Ngoc Lan Saigon Hospital", "Ho Chi Minh City", "PAIR09"),
        ("Bệnh viện Ngọc Lan Đà Nẵng", "Ngoc Lan Da Nang Hospital", "Da Nang", "PAIR09"),
        (
            "Bệnh viện Đa khoa Quốc tế Cẩm Tú Long Biên",
            "Cam Tu Long Bien International Hospital",
            "Hanoi",
            "PAIR10",
        ),
        (
            "Bệnh viện Đa khoa Quốc tế Cẩm Tú Thủ Đức",
            "Cam Tu Thu Duc International Hospital",
            "Ho Chi Minh City",
            "PAIR10",
        ),
    ]:
        s.append(
            _vn(
                "private_hospital",
                local,
                english,
                city,
                pair_key=pair,
                legal=f"Công ty Cổ phần {local}",
            )
        )
    s.append(
        _vn(
            "laboratory",
            "Merlion Diagnostics Việt Nam",
            "Merlion Diagnostics Vietnam",
            "Ho Chi Minh City",
            legal="Công ty TNHH Merlion Diagnostics Việt Nam",
            group_id="GRP02",
        )
    )
    s.append(
        _vn(
            "clinic",
            "Phòng khám Mekong Health Cần Thơ",
            "Mekong Health Clinic Can Tho",
            "Can Tho",
            group_id="GRP04",
        )
    )

    # ---------------- Thailand ----------------
    s.append(
        _th(
            "public_hospital",
            "โรงพยาบาลศิริราช",
            "Siriraj Hospital",
            "Bangkok",
            key=SIRIRAJ,
            forced_card_name="โรงพยาบาลศิริราช",
        )
    )
    for local, english, city in [
        ("โรงพยาบาลรามาธิบดี", "Ramathibodi Hospital", "Bangkok"),
        ("โรงพยาบาลจุฬาลงกรณ์", "King Chulalongkorn Memorial Hospital", "Bangkok"),
        ("โรงพยาบาลราชวิถี", "Rajavithi Hospital", "Bangkok"),
        ("โรงพยาบาลพระมงกุฎเกล้า", "Phramongkutklao Hospital", "Bangkok"),
        ("โรงพยาบาลมหาราชนครเชียงใหม่", "Maharaj Nakorn Chiang Mai Hospital", "Chiang Mai"),
        ("โรงพยาบาลสงขลานครินทร์", "Songklanagarind Hospital", "Hat Yai"),
        ("โรงพยาบาลศรีนครินทร์", "Srinagarind Hospital", "Khon Kaen"),
        ("โรงพยาบาลภูมิพลอดุลยเดช", "Bhumibol Adulyadej Hospital", "Bangkok"),
        ("โรงพยาบาลเลิดสิน", "Lerdsin Hospital", "Bangkok"),
        ("โรงพยาบาลนพรัตนราชธานี", "Nopparat Rajathanee Hospital", "Bangkok"),
        ("โรงพยาบาลตำรวจ", "Police General Hospital", "Bangkok"),
        ("โรงพยาบาลวชิรพยาบาล", "Vajira Hospital", "Bangkok"),
        ("โรงพยาบาลขอนแก่น", "Khon Kaen Hospital", "Khon Kaen"),
        ("โรงพยาบาลชลบุรี", "Chonburi Hospital", "Chonburi"),
        ("โรงพยาบาลนครปฐม", "Nakhon Pathom Hospital", "Nakhon Pathom"),
        ("โรงพยาบาลมหาราชนครราชสีมา", "Maharat Nakhon Ratchasima Hospital", "Nakhon Ratchasima"),
    ]:
        s.append(_th("public_hospital", local, english, city))
    for local, english, city, pair in [
        ("โรงพยาบาลแสงตะวันพัทยา", "Saeng Tawan Hospital Pattaya", "Pattaya", "PAIR12"),
        ("โรงพยาบาลแสงตะวันภูเก็ต", "Saeng Tawan Hospital Phuket", "Phuket", "PAIR12"),
        ("โรงพยาบาลบัวขาว สุขุมวิท", "Bua Khao Sukhumvit Hospital", "Bangkok", "PAIR13"),
        ("โรงพยาบาลบัวขาว ศรีนครินทร์", "Bua Khao Srinakarin Hospital", "Bangkok", "PAIR13"),
        ("โรงพยาบาลพิมาน 1", "Phiman 1 Hospital", "Bangkok", "PAIR14"),
        ("โรงพยาบาลพิมาน 2", "Phiman 2 Hospital", "Bangkok", "PAIR14"),
    ]:
        s.append(_th("private_hospital", local, english, city, pair_key=pair))
    s.append(
        _th(
            "private_hospital",
            "ศูนย์การแพทย์อันดามัน ภูเก็ต",
            "Andaman Medical Centre Phuket",
            "Phuket",
            group_id="GRP03",
        )
    )
    s.append(
        make_spec(
            "TH",
            "laboratory",
            "เมอร์ไลออน ไดแอกนอสติกส์",
            "Merlion Diagnostics Thailand",
            legal="บริษัท เมอร์ไลออน ไดแอกนอสติกส์ (ประเทศไทย) จำกัด",
            legal_rom="Merlion Diagnostics (Thailand) Co., Ltd.",
            city="Bangkok",
            group_id="GRP02",
            lang_alts=("Merlion Diagnostics Thailand",),
        )
    )
    s.append(
        _th(
            "clinic",
            "เมคอง เฮลท์ คลินิก อุดรธานี",
            "Mekong Health Clinic Udon Thani",
            "Udon Thani",
            group_id="GRP04",
        )
    )
    for site in ["Novena", "Jurong East"]:
        s.append(
            make_spec(
                "SG",
                "laboratory",
                f"Lion City Pathology {site}",
                legal=f"Lion City Pathology ({site}) Pte Ltd",
                city="Singapore",
                pair_key="PAIR15",
            )
        )
    return s
