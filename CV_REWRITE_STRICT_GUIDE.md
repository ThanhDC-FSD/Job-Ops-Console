# CV Rewrite Strict Guide

## 0) Execution Contract (Bat buoc thong nhat)
- Moi lan chay prompt phai theo dung 1 quy trinh, khong doi format theo tung lan.
- Cau truc output, ten file, ten section report, va logic danh gia phai giu nguyen theo guide nay.
- Trong fit report:
1. `PASS` phai hien thi mau xanh (dung the HTML: `**🟢 PASS**`).
2. `FAIL` phai hien thi mau do (dung the HTML: `**🔴 FAIL**`).
3. Luon co 2 muc: `Prerequisite Check (Part-time + Remote)` va `Daily Comparison (YYMMDD)`.
## 1) Muc tieu
- Tao CV toi uu theo tung JD voi dau vao co dinh:
1. `input/full_doc_stlye.txt` (master CV day du kinh nghiem)
2. `input/JD/<jd_input>.txt` (JD can apply)
3. Thong tin bo sung nguoi dung cung cap them (neu co)
- Dau ra bat buoc:
1. Tao folder: `input/Raw_CV/<time_stamp (YYMMDD)>_<ID>_<jd_input>/`
2. File CV text: `input/Raw_CV/<time_stamp (YYMMDD)>_<ID>_<jd_input>/CV_<jd_input>.txt`
3. File cover letter: `input/Raw_CV/<time_stamp (YYMMDD)>_<ID>_<jd_input>/cover_letter_<jd_input>.txt`
4. File fit report: `input/Raw_CV/<time_stamp (YYMMDD)>_<ID>_<jd_input>/<jd_input>_fit_report.md`
5. (Tuy chon) file style trung gian: `input/full_doc_style_<jd_input>.txt`

## 2) Nguyen nhan fail pho bien (rut tu case JD Electrical)
- CV headline lech huong JD.
- Thieu truong bat buoc theo JD (vi du: English level, degree, location constraint).
- Evidence ky thuat co, nhung cach trinh bay khong khop keyword/expectation trong JD.
- Qua nhieu bullet noise khong lien quan.
- Chua neu ro risk constraint (vi du: chi nhan candidate o mot quoc gia cu the).

## 3) Nguyen tac bat buoc (khong duoc vi pham)
- Khong duoc bia thong tin, khong them thanh tich/chung chi neu chua duoc xac nhan.
- Toan bo output tao ra phai la tieng Anh: CV text, cover letter, headline, summary, experience summary, notes, va fit-facing explanation.
- Moi bullet phai lien ket den it nhat 1 requirement trong JD.
- Uu tien evidence co the kiem chung (project, vai tro, timeline, cong nghe).
- Van giu dinh dang tag renderer dang dung (`<bold>`, `<italic>`, `<green>`, `<orange>`, `<center>`, `<size:n>`).
- Duoc phep thay doi cach viet, thu tu, va cach the hien tu cung mot du lieu goc de phu hop JD tot nhat.
- Khong thay doi ban chat su that; chi duoc "reframe", khong duoc "invent".
- Duoc phep sang tao manh hon trong cach dien dat va dong goi evidence, mien la moi y van truy vet duoc ve thong tin goc trong master CV/JD.
- Neu co nhieu cach viet deu dung su that, uu tien cach viet khiem recruiter cam thay candidate fit hon voi role.
- Hard constraint ca nhan: chi nhan role `part-time` + `remote`; JD khac dieu kien nay duoc danh gia `khong phu hop`.

## 4) Quy trinh tao CV

### B1. Parse JD thanh rubric
- Tach JD thanh nhom:
1. Must-have (bat buoc)
2. Strong preferred (uu tien cao)
3. Nice-to-have (cong diem)
4. Constraints (location, legal, working model, language, salary type)
- Rubric de cham:
1. Domain/Experience fit: 35%
2. Core technical fit: 30%
3. Evidence quality: 20%
4. Compliance with JD constraints: 15%

### B2. Trich xuat inventory tu `full_doc_stlye.txt`
1. Vai tro + timeline
2. Skills/tooling
3. Project evidence
4. Education/certifications/English level/location (neu co)

### B3. Map `JD requirement -> CV evidence`
- Trang thai cho tung requirement:
1. `Strong match`
2. `Partial match`
3. `Missing`
- Neu la `Strong match` hoac `Partial match` co gia tri cao, phai viet ra ro rang trong CV thay vi de recruiter tu suy ra.
- Uu tien goi ten overlap cu the: stack, API/backend pattern, testing, cloud/devops, ownership, stakeholder scope, system scale, hoac domain behavior neu co bang chung.
- Voi `Missing`:
1. Xin bo sung thong tin tu user neu can
2. Neu khong co thong tin thi giu trung thuc, neu ro limitation
 3. Neu requirement la cong nghe/stack chua co kinh nghiem truc tiep (vd: `.NET`, `C#`, mot cloud/provider khac), phai map sang:
    - stack gan nhat da tung lam
    - kinh nghiem backend/API/system design/testing/deployment co the chuyen doi
    - bang chung da hoc va delivery trong nhieu stack/nganh khac nhau
 4. Khong duoc viet nhu the da co kinh nghiem truc tiep neu CV goc khong xac nhan.
 5. Muc tieu la giam nguy co bi reject som: van trung thuc, nhung phai cho recruiter thay "vi sao nen doc ky CV nay".

### B4. Viet CV moi theo JD
- Dau ra bat buoc:
1. Tao bien `run_folder = input/Raw_CV/<time_stamp (YYMMDD)>_<ID>_<jd_input>/`.
2. Quy tac ID: ID tang dan trong cung 1 ngay (01, 02, 03, ...); sang ngay moi thi reset lai tu 01.
3. Tao folder `run_folder` neu chua ton tai.
4. CV: `run_folder/CV_<jd_input>.txt`
5. Cover letter: `run_folder/cover_letter_<jd_input>.txt`
- Cau truc de xuat:
1. Header/Title match JD
2. Summary ngan (3-4 dong)
3. Work Experience (uu tien bullet match JD)
4. Technical Skills (loc theo JD)
5. Core Competencies (neu can)
6. Education/Certifications/English (neu JD yeu cau)
- Quy tac bullet:
1. Action verb dau dong
2. Co context
3. Co tool/tech
4. Co impact neu co du lieu
5. Mot bullet mot thong diep
6. Cho phep tong hop nhieu bang chung lien quan thanh 1 bullet manh hon neu van trung thuc va truy vet duoc ve CV goc
7. Neu bullet dang cover mot diem overlap quan trong voi JD, viet thang overlap do bang ngon ngu ro rang va gan voi cach JD goi ten
- Quy tac xu ly gap:
1. Neu thieu exact-match tech, khong che tao match gia.
2. Viet theo cong thuc: `adjacent evidence -> transferable relevance -> ramp-up confidence`.
3. Trong Summary/cover letter, neu role can stack chua lam truc tiep, phai neu ro:
   - nen tang backend/full-stack co lien quan
   - kha nang hoc nhanh/co deliver tren stack moi neu co evidence tu CV goc
   - dong co muon lam viec tai cong ty do, vi sao muon tham gia team/doanh nghiep do
   - tinh than san sang dong gop lau dai, on dinh, va tao gia tri thuc te cho team
   - ly do recruiter van nen giu ho so o vong review thay vi loai som
4. Vi du mong muon:
   - Khong viet: `3 years of .NET experience` neu khong co that.
   - Nen viet: `Strong backend API and delivery background across Java/Python systems with transferable service design, testing, and production support skills; ready to ramp quickly into .NET if selected.`
   - Tot hon nua: `Strong backend API and delivery background across Java/Python systems with transferable service design, testing, and production support skills; ready to ramp quickly into .NET if selected, and motivated to contribute long-term to the team's engineering goals.`
5. Nguyen tac "creative but true":
   - Co the doi cach goi ten nang luc cho sat JD hon (`service delivery`, `platform ownership`, `production engineering`, `cross-functional delivery`, ...)
   - Co the sap xep lai bullet/section de evidence gan nhat voi JD len truoc
   - Co the tong hop evidence roi viet theo huong thuyet phuc hon
   - Khong duoc them skill, title, scope, metric, hay thoi gian neu CV goc khong xac nhan

### B5. ATS + reviewer gate (pass/fail)
- Gate 1: 100% must-have co trong CV.
- Gate 2: Khong thieu keyword quan trong trong JD.
- Gate 3: Khong co bullet noise.
- Gate 4: Constraints duoc neu ro (vi du location eligibility).
- Gate 5: Title/Summary khong mau thuan voi role muc tieu.
- Gate 6 (hard): JD phai co ca `part-time` va `remote`; neu fail thi dung quy trinh ung tuyen role do.

### B6. Cham diem truoc khi chap nhan
1. `>= 85`: San sang apply
2. `70-84`: Can sua them
3. `< 70`: Khong nen apply ngay
- Bat buoc ghi ly do tru diem theo nhom.

### B7. Chay script danh gia do phu hop (bat buoc)
- Script: `scripts/python/evaluate_cv_fit.py`
- Lenh mau:
```bash
$env:PYTHONHOME=''; $env:PYTHONPATH=''; .\.venv\Scripts\python.exe scripts/python/evaluate_cv_fit.py --jd "input/JD/<jd_input>.txt" --cv "input/Raw_CV/<time_stamp (YYMMDD)>_<ID>_<jd_input>/CV_<jd_input>.txt" --report "input/Raw_CV/<time_stamp (YYMMDD)>_<ID>_<jd_input>/<jd_input>_fit_report.md"
```
- Neu score < 85, phai quay lai B3-B4 de toi uu them truoc khi apply.
- Neu script tra ve `NOT COMPATIBLE` thi ket luan ngay: role khong phu hop do hard constraint (part-time remote).
- Fit report bat buoc phai co muc `Prerequisite Check (Part-time + Remote)` voi ket qua `PASS/FAIL`.
- Fit report bat buoc phai co muc `Daily Comparison (YYMMDD)` va ket luan `Best-fit JD today`.
- `PASS` hien thi bang `**🟢 PASS**` va `FAIL` hien thi bang `**🔴 FAIL**` trong report (`Prerequisite Check` va `Daily Comparison`).

## 5) Template output
```txt
<bold><center>DINH CONG THANH</center></bold>
<center><Target Title Aligned With JD></center>
<center>thanhdc.dev@gmail.com | (+84) 96 552 8181 | Hanoi, Vietnam | English: <level></center>

<bold><green>Professional Summary</green></bold>
...

Neu co requirement bi thieu exact-match, Summary nen uu tien 1 cau theo mau:
- `Bring strong adjacent experience in <nearby stack/domain>, with proven ability to ramp quickly into new tooling while maintaining delivery quality.`
- Neu phu hop, them 1 cau reviewer-facing: `Motivated to join <company/team> and contribute durable engineering value over the long term.`
- Neu co overlap ro voi JD, them 1 cau kieu: `Directly aligns with <shared responsibility/tooling/domain need> through prior work in <relevant evidence>.`

<bold><green>Work Experience</green></bold>
...

<bold><green>Technical Skills</green></bold>
...
```

## 6) Checklist van hanh moi lan tao CV
1. Xac dinh dung file JD (`input/JD/<jd_input>.txt` hoac file user chi dinh).
2. Tao rubric + ma tran match.
3. Liet ke `Missing`/`Constraint risk`.
4. Tao `time_stamp` theo format `YYMMDD`.
5. Xac dinh `ID` theo ngay:
   - Lay ID lon nhat da co trong ngay `time_stamp` trong `input/Raw_CV/`
   - ID moi = ID lon nhat + 1 (pad 2 chu so, vd: 01, 02)
   - Neu chua co folder trong ngay do thi ID = 01
6. Tao folder `input/Raw_CV/<time_stamp>_<ID>_<jd_input>/`.
7. Viet file CV vao `input/Raw_CV/<time_stamp>_<ID>_<jd_input>/CV_<jd_input>.txt`.
8. Tao file cover letter `input/Raw_CV/<time_stamp>_<ID>_<jd_input>/cover_letter_<jd_input>.txt`.
9. Chay script:
`$env:PYTHONHOME=''; $env:PYTHONPATH=''; .\.venv\Scripts\python.exe scripts/python/evaluate_cv_fit.py --jd "input/JD/<jd_input>.txt" --cv "input/Raw_CV/<time_stamp>_<ID>_<jd_input>/CV_<jd_input>.txt" --report "input/Raw_CV/<time_stamp>_<ID>_<jd_input>/<jd_input>_fit_report.md"`
10. Tu cham diem theo rubric + doi chieu voi fit report.
11. Bao cao:
- Diem tong + diem tung nhom
- Requirement da cover/chua cover
- Risk con lai truoc khi apply
- JD phu hop nhat trong ngay (trich tu muc `Daily Comparison` trong report)

## 7) Goi y phat trien guide tiep theo
- Them bang keyword mapping theo tung nganh (SaaS, Data, Embedded, AI, Electrical, etc.).
- Them "ban list risk tu choi som" (hard constraints) de tranh ton thoi gian apply.
- Them schema YAML/JSON cho rubric de tu dong hoa cham diem.
- Them script validate CV text:
1. check keyword coverage
2. check section order
3. check output path rule (`input/Raw_CV/`)
- Them A/B template strategy:
1. ATS-optimized version
2. Human-review optimized version


## Example Usage (Prompt Template)

Note:
- This section is a reusable prompt template for the user.
- It is not a default task that must be executed automatically.
- The assistant should execute it only when the user explicitly asks.

Prompt example:
"Bay gio hay dua vao cac dau vao [full_doc_stlye.txt](input/full_doc_stlye.txt) + jd [jd_Shopify_Plus.txt](input/JD/jd_Shopify_Plus.txt) cung voi file [CV_REWRITE_STRICT_GUIDE.md](CV_REWRITE_STRICT_GUIDE.md), thuc hien cac cong viec trong guide."




