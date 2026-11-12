"""ESPN'den gelen takım ve ülke adlarının Türkçe karşılıkları. Listede olmayan adlar olduğu gibi kalır."""

KULUP = {
    "Besiktas": "Beşiktaş", "Fenerbahce": "Fenerbahçe", "Goztepe": "Göztepe", "Kasimpasa": "Kasımpaşa",
    "Caykur Rizespor": "Çaykur Rizespor", "Genclerbirligi": "Gençlerbirliği", "Istanbul Basaksehir": "Başakşehir",
    "Eyupspor": "Eyüpspor", "Erzurum BB": "Erzurumspor", "Amed SFK": "Amedspor", "Çorum FK": "Çorum FK",
    "Ankaragucu": "Ankaragücü", "Istanbulspor": "İstanbulspor",
    # Avrupa kulüplerinin Türkçede yerleşik adları
    "Bayern Munich": "Bayern Münih", "FC Cologne": "Köln", "Red Star Belgrade": "Kızılyıldız",
    "Paris Saint-Germain": "Paris Saint-Germain", "Internazionale": "Inter", "AS Roma": "Roma", "AC Milan": "Milan",
    "Atletico Madrid": "Atletico Madrid", "Sporting CP": "Sporting Lizbon", "FC Porto": "Porto",
    "Slavia Prague": "Slavia Prag", "Sparta Prague": "Sparta Prag", "Dinamo Zagreb": "Dinamo Zagreb",
    "Shakhtar Donetsk": "Şahtar Donetsk", "Dynamo Kyiv": "Dinamo Kiev", "FC Copenhagen": "Kopenhag",
    "Olympiacos": "Olimpiakos", "Panathinaikos": "Panathinaikos", "AEK Athens": "AEK", "PAOK Salonika": "PAOK",
    "Feyenoord Rotterdam": "Feyenoord", "Ajax Amsterdam": "Ajax", "PSV Eindhoven": "PSV",
}

ULKE = {
    "Afghanistan": "Afganistan", "Albania": "Arnavutluk", "Algeria": "Cezayir", "American Samoa": "Amerikan Samoası",
    "Andorra": "Andorra", "Angola": "Angola", "Antigua and Barbuda": "Antigua ve Barbuda", "Argentina": "Arjantin",
    "Armenia": "Ermenistan", "Australia": "Avustralya", "Austria": "Avusturya", "Azerbaijan": "Azerbaycan",
    "Bahamas": "Bahamalar", "Bahrain": "Bahreyn", "Bangladesh": "Bangladeş", "Belarus": "Belarus", "Belgium": "Belçika",
    "Bolivia": "Bolivya", "Bosnia-Herzegovina": "Bosna-Hersek", "Botswana": "Botsvana", "Brazil": "Brezilya",
    "Brunei Darussalam": "Brunei", "Bulgaria": "Bulgaristan", "Cambodia": "Kamboçya", "Cameroon": "Kamerun",
    "Canada": "Kanada", "Cape Verde": "Yeşil Burun Adaları", "Cayman Islands": "Cayman Adaları",
    "Central African Republic": "Orta Afrika Cumhuriyeti", "Chad": "Çad", "Chile": "Şili", "China": "Çin",
    "Chinese Taipei": "Çin Taypeyi", "Colombia": "Kolombiya", "Comoros": "Komorlar", "Congo": "Kongo",
    "Congo DR": "Kongo DC", "Costa Rica": "Kosta Rika", "Croatia": "Hırvatistan", "Cuba": "Küba", "Cyprus": "Kıbrıs",
    "Czechia": "Çekya", "Denmark": "Danimarka", "Djibouti": "Cibuti", "Dominican Republic": "Dominik Cumhuriyeti",
    "Ecuador": "Ekvador", "Egypt": "Mısır", "England": "İngiltere", "Equatorial Guinea": "Ekvator Ginesi",
    "Eritrea": "Eritre", "Estonia": "Estonya", "Eswatini": "Esvatini", "Ethiopia": "Etiyopya",
    "Faroe Islands": "Faroe Adaları", "Finland": "Finlandiya", "France": "Fransa", "French Guiana": "Fransız Guyanası",
    "Gambia": "Gambiya", "Georgia": "Gürcistan", "Germany": "Almanya", "Ghana": "Gana", "Gibraltar": "Cebelitarık",
    "Greece": "Yunanistan", "Guinea": "Gine", "Guinea-Bissau": "Gine-Bissau", "Hungary": "Macaristan",
    "Iceland": "İzlanda", "India": "Hindistan", "Indonesia": "Endonezya", "Iran": "İran", "Iraq": "Irak",
    "Israel": "İsrail", "Italy": "İtalya", "Ivory Coast": "Fildişi Sahili", "Jamaica": "Jamaika", "Japan": "Japonya",
    "Jordan": "Ürdün", "Kazakhstan": "Kazakistan", "Kosovo": "Kosova", "Kuwait": "Kuveyt",
    "Kyrgyz Republic": "Kırgızistan", "Latvia": "Letonya", "Lebanon": "Lübnan", "Liberia": "Liberya", "Libya": "Libya",
    "Liechtenstein": "Lihtenştayn", "Lithuania": "Litvanya", "Luxembourg": "Lüksemburg", "Macau": "Makao",
    "Malaysia": "Malezya", "Maldives": "Maldivler", "Mauritania": "Moritanya", "Mexico": "Meksika",
    "Moldova": "Moldova", "Mongolia": "Moğolistan", "Montenegro": "Karadağ", "Morocco": "Fas", "Mozambique": "Mozambik",
    "Namibia": "Namibya", "Netherlands": "Hollanda", "New Caledonia": "Yeni Kaledonya", "New Zealand": "Yeni Zelanda",
    "Niger": "Nijer", "Nigeria": "Nijerya", "North Korea": "Kuzey Kore", "North Macedonia": "Kuzey Makedonya",
    "Northern Ireland": "Kuzey İrlanda", "Norway": "Norveç", "Oman": "Umman", "Palestine": "Filistin",
    "Papua New Guinea": "Papua Yeni Gine", "Philippines": "Filipinler", "Poland": "Polonya", "Portugal": "Portekiz",
    "Puerto Rico": "Porto Riko", "Qatar": "Katar", "Republic of Ireland": "İrlanda", "Romania": "Romanya",
    "Russia": "Rusya", "Rwanda": "Ruanda", "Saudi Arabia": "Suudi Arabistan", "Scotland": "İskoçya",
    "Serbia": "Sırbistan", "Seychelles": "Seyşeller", "Singapore": "Singapur", "Slovakia": "Slovakya",
    "Slovenia": "Slovenya", "Solomon Islands": "Solomon Adaları", "Somalia": "Somali", "South Africa": "Güney Afrika",
    "South Korea": "Güney Kore", "South Sudan": "Güney Sudan", "Spain": "İspanya", "Sweden": "İsveç",
    "Switzerland": "İsviçre", "Syria": "Suriye", "Tajikistan": "Tacikistan", "Tanzania": "Tanzanya",
    "Thailand": "Tayland", "Timor-Leste": "Doğu Timor", "Trinidad and Tobago": "Trinidad ve Tobago", "Tunisia": "Tunus",
    "Turkmenistan": "Türkmenistan", "Ukraine": "Ukrayna", "United Arab Emirates": "Birleşik Arap Emirlikleri",
    "United States": "ABD", "Uzbekistan": "Özbekistan", "Wales": "Galler", "Yemen": "Yemen", "Zambia": "Zambiya",
    "Zimbabwe": "Zimbabve",
}


def cevir(ad, milli=False):
    return (ULKE.get(ad) if milli else None) or KULUP.get(ad, ad)
