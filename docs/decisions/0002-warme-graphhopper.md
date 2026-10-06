# 0002 — Altijd-warme GraphHopper achter een schakelaar

- Status: aangenomen, uitrol en metingen nog uit te voeren
- Datum: 6 oktober 2026
- Issue: #19

## Context

GraphHopper in de API-Lambda heeft koude starts, deelt 3008 MB met Python en
vraagt zonder CH/LM ongeveer 2 s per routeraanvraag. Een klimroute van 60 km
kan daardoor minuten duren. De eigenaar heeft de vaste kosten goedgekeurd.
De standaardarchitectuur uit docs/AWS.md blijft beschikbaar voor rollback.

## Beslissing

Voeg één altijd-warme Amazon Linux 2023 x86_64 EC2 toe (standaard t3.large),
in de default VPC, met een versleuteld gp3-volume voor de graph-cache. User-data
haalt het regiopack uit dezelfde TF-statebucket/S3-sleutel als Deploy AWS.
Pack-SHA256 bindt de voorbereiding aan de gevalideerde deployment; packversies
hebben aparte caches. De cache blijft bewaard bij reboot of instancevervanging.

GraphHopper 11.0 draait via Docker met de packconfig plus Landmarks voor quiet
en trail. CH blijft uit wegens request-time custom models. LM blijft bruikbaar
omdat alle requestregels alleen straffen (priority ≤ 1); offline tests dekken
alle activiteiten, booleans, heat- en area-opties. Ongeldige vermijdfactoren
worden geweigerd. De lokale config en het pack zelf krijgen geen LM-wijziging.
LM-preparatie gebeurt eenmaal per pack op de instantie; **duur en geheugen:
te meten**. Herstarts hergebruiken dezelfde voorbereiding.

Lambda blijft buiten een VPC. CloudFront biedt HTTPS met het standaardcertificaat,
geen caching en alle methodes, met een HTTP-origin op poort 80. nginx controleert
het door de client aangeleverde X-Ommeke-Origin-geheim; CloudFront voegt geen
geheim toe. De SG accepteert alleen CloudFront origin-facing. Docker bindt
GH aan loopback. Het instanceprofile kan alleen het gekozen S3-pack lezen.

Alle resources en lookups staan achter gh_service_enabled (default false).
Met false blijft de Lambda-env gelijk. Met true krijgt ze GH_URL en het
random_password-geheim; de entrypoint slaat graphkopie en JVM over. De client
stuurt de header bij routes, info en health. De bestaande router=1-smoke volgt
automatisch dezelfde gekozen URL.

## Gevolgen

- Kostenraming: eu-west-1 t3.large on-demand ≈ $0,0912/u ≈ $67/maand,
  plus graph- en rootvolume, CloudFront, publiek IPv4 en mogelijke CPU-credits.
  Dit doorbreekt scale to zero voor de router, niet voor de API-Lambda.
- Eén instantie is één uitvalpunt; geen HA of automatische failover in deze taak.
- Geen NAT of Lambda-VPC; de instantie heeft publiek IPv4 voor pack/image-downloads.
- Het geheim staat in beveiligde Terraform-state/plan, Lambda-env, EC2-user-data
  en nginx-config; geen geheime output of accesslogging.
- Packwissels vervangen de instantie en kunnen tijdelijke routeruitval geven.
  Oude packcaches nemen blijvend schijfruimte in; bewaak de capaciteit.
- Een digestrollback hergebruikt de routerkeuze en het huidige S3-pack;
  een packrollback vereist het vorige pack terugzetten en opnieuw deployen.

## Uitrol en rollback

De eigenaar past eerst infra/bootstrap één keer met admin toe, zet daarna
GH_SERVICE_ENABLED=true (of TF_VAR_gh_service_enabled=true plus packbucket/SHA),
rolt via Deploy AWS uit en controleert de router=1-smoke. Meet p50/p95 van
representatieve routes, koud/warm, LM-preparatieduur en geheugen. Verlaag pas
na die metingen Lambda-geheugen. Exacte stappen staan in docs/AWS.md.

Rollback: herstel zo nodig Lambda-geheugen naar 3008 MB, schakel
GH_SERVICE_ENABLED uit en deploy opnieuw. Lambda start weer lokale GH;
Terraform verwijdert de service inclusief graphvolume. De S3-bronpack blijft.

Er zijn tijdens deze implementatie geen AWS-resources toegepast, geen live
smoke-tests uitgevoerd en geen latentie- of geheugencijfers gemeten.
