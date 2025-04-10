# Topograf

![Topograf](/res/topograf.png)

#### Preizkusite na: [https://topograf.scuke.si](https://topograf.scuke.si)

## Kaj je Topograf?

Topograf je uporabniku prijazno orodje za ustvarjanje lepih topografskih zemljevidov. Ne glede na to, ali načrtujete pohod, orientacijsko tekmovanje, poučujete vrisovanje ali vas le zanima raziskovanje terena, Topograf omogoča enostavno ustvarjanje profesionalnih kartt s prilagodljivimi funkcijami.

### Primer zemljevida

![Vzorčni zemljevid](/res/created_preview.png)

## Kako začeti

1. Obiščite [topograf.scuke.si](https://topograf.scuke.si)
2. Izberite območje, ki vas zanima na zemljevidu
3. Prilagodite nastavitve zemljevida (stil mreže, oznake, itd.)
4. Ustvarite in prenesite svoj osebni topografski zemljevid

## Funkcije

- **Interaktivna izbira območja**: Izberite točno tisto območje, ki ga želite izrisati
- **Prilagodljiv naslov**: Dodajte naslov in opis svojemu zemljevidu
- **Prilagodljive mreže**: Dodajte koordinatne mreže v različnih koordinatnih sistemih
- **Oznake kontrolnih točk**: Poudarite specifične lokacije z lastnimi oznakami
- **Izvoz v PDF**: Prenesite visokokakovostne zemljevide, pripravljene za tiskanje (A4, A4)
- **Izvoz kontrolnih točk**: Prenesite seznam kontrolnih točk z njihovimi koordinatami in pobližano sliko lokacije

## Kako deluje

Topograf združuje geografske podatke z vašimi nastavitvami za ustvarjanje podrobnih zemljevidov. Sistem obdeluje vaše izbire s pomočjo dveh glavnih komponent:

Osrednji sistem za generiranje zemljevidov poskrbi za vse tehnične podrobnosti namesto vas - od obdelave geografskih podatkov do risanja končnega zemljevida z vsemi izbranimi funkcijami.

### Spletni vmesnik

Uporabniku prijazen spletni vmesnik vam omogoča:
- Določitev mej zemljevida
- Predogled zemljevida pred ustvarjanjem
- Prilagajanje funkcij in videza zemljevida
- Dostop in prenos ustvarjenih zemljevidov

### Tiskanje

Zemljevide lahko natisnete na A4 ali A3 formatu, pri tisku bodite pozorni na nastavitve tiskalnika (npr. prilagoditev velikosti zemljevida). Velikost strani naj bo nastavljena na 100% in brez obrezovanja.

### Inštalacija
Za lokalno inštalacijo Topografa potrebujete Node.js 20+, npm in python 3.12+. Uporabite naslednje ukaze za namestitev in zagon aplikacije:

```bash
# Frontend+Backend
npm install # Install dependencies
npm run build # Build server

# Create map
cd create_map # Go to create_map folder
python -m venv .venv # Create virtual environment
source .venv/bin/activate # Activate virtual environment
pip install -r requirements.txt # Install requirements

cp .env.template .env # Copy .env template to .env
nano .env # Edit .env file with your settings

# Run server
node build
```

### Potrebni rasterski sloji

Za pravilno delovanje Topografa potrebujete rasterske sloje, ki jih lahko prensete [tukaj](https://drive.google.com/drive/folders/1am-GfSFqO4bFyvkq0LJMC5hzDUnihQVu?usp=drive_link).