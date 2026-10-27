# Örnek istemler (tetikleme ve kademe seçimi için değerlendirme seti)

Claude Code'da `/andes-agent-skill <istem>` ile ya da doğrudan doğal dille kullanılır. Parantez içindeki kademe, beklenen seçimdir.

## Hızlı kademe

- `IEEE 14 yerleşik vakasında güç akışı çalıştır ve 0.95 pu altındaki baraları listele; 0.95 pu benim tarama eşiğim.` (hızlı)
- `Kundur vakasında 2 numaralı baraya bağlı jeneratör hangisi, eylemsizlik sabiti M kaç?` (hızlı; yalnızca inceleme)
- `Kundur'da bara 5'te 1.0 s'de xf=1e-6 ile üç faz arıza uygula, 1.1 s'de temizle, 5 s çalıştır.` (hızlı; TDS başarısız olmalı ve başarısızlık olarak raporlanmalı, sessiz düzeltme yapılmamalı)

## Standart kademe

- `IEEE 14 bara yerleşik vakasında güç akışı çalıştır. Bara gerilim ve açılarını CSV'ye yaz. 0.95 pu sınırı bu çalışma için kullanıcı kriteridir; altındaki baraları raporla. Sonuç tekrarlanabilir olsun.`
- `Kundur tam dinamik vakasında mevcut Toggle olayını devre dışı bırak. Bara 5'te t=1.0 s anında üç faz arıza uygula, 100 ms sonra temizle, 5 s çalıştır. GENROU hızlarını ve bara gerilimlerini CSV/PNG çıkar.`
- `Bu RAW ve DYR dosyalarını önce incele. 2 numaralı baraya bağlı dinamik jeneratörü gerçek idx ile çöz. 1-2 s arasında paux değerini 0.05 pu yap, sonra sıfıra döndür.`
- `IEEE 14 sisteminde tüm bara gerilimleri ve P/Q enjeksiyonlarından WLS durum kestirimi yap. Tohum 42. İlk ölçüme 10 sigma hata ekle ve chi-square testini raporla. Aynı ölçüm setini LAV ile ayrı işte karşılaştır.`
- `IEEE 14 sisteminde PV burun eğrisi ile 14 numaralı baranın QV eğrisini ayrı taze sistem nesneleriyle üret. Q limitlerini açacaksak bunu ayrı senaryo olarak belirt.`

## Araştırma kademesi

- `Kundur sisteminde küçük işaret analizi yap. EXDC2 KA parametresini 20-200 arasında süpür; izlenecek mod indekslerini EIG raporunu gördükten sonra seç, uydurma.`
- `Bu vakadaki bütün hatları envanterle. N-1 çalışmasını hemen başlatma; önce tek hat smoke test ve kararlılık kriterleri için benden onay al.`
- `Kundur'da bara 7 arızası için kritik temizleme süresini bul; kararlılık ölçütü olarak makaledeki rotor açısı farkı sınırını kullanacağım.` (ölçüt ve kaynağı sorulmalı)
- `Yeni bir dinamik model geliştirmek istiyorum. Önce model denklemleri, parametreler, initialization hedefleri ve referans testini yazılı hale getir; sonra model iskeletini üret.`
