# Báo cáo tổng hợp kết quả crawl bệnh

Ngày tổng hợp: 2026-08-03

Nguồn: `state/crawler.db` và các artifact còn lưu trong `output/jobs`

## Kết luận

- Database ghi nhận **8 lần chạy**.
- Có **5 job còn đầy đủ report và import audit**; artifact của 3 job cũ đã được
  xóa theo yêu cầu trước đó.
- Năm import audit còn lưu chứa **80 tên bệnh đầu vào duy nhất**.
- **67/80 tên đầu vào đã được xác nhận có kết quả** — tỷ lệ 83,75%.
- **13/80 tên đầu vào chưa crawl được** — tỷ lệ 16,25%.
- Database có **123 canonical URL** từng đạt trạng thái `parsed`.
- Có 23 URL chỉ xuất hiện trong job `c5a63f00...` bị nhiễu autocomplete và chạm
  `category_node_limit`; các URL này không được tính vào kết quả tin cậy.
- Kết quả tin cậy còn **100 canonical disease pages**, tương ứng **99 tên bệnh
  duy nhất**. Tên `Gout` có hai canonical URL khác nhau.

Con số nên sử dụng cho nghiệp vụ là: **đã crawl được 99 loại bệnh; còn 13 tên
đầu vào chưa crawl được**.

## Phương pháp tính

1. Chỉ tính item có `status = parsed` và `data_complete = true`.
2. Khử trùng lặp theo `canonical_url` để tính số trang bệnh.
3. Khử trùng lặp theo tiêu đề chuẩn hóa để tính số loại bệnh.
4. Job `c5a63f00-5d32-490e-badb-1993fa8edd40` không được dùng độc lập vì đã
   xác nhận có kết quả tìm kiếm sai liên quan đến UTI và dừng ở 100 node.
5. URL của job lỗi vẫn được tính nếu xuất hiện lại trong một job hoàn tất không
   chạm giới hạn, đặc biệt là job chạy lại `ffb80fbb...`.
6. Danh sách chưa crawl được lấy từ trạng thái cuối cùng của từng tên trong
   `import-search.json`. Nếu một tên thất bại ở lần trước nhưng thành công ở lần
   chạy lại, tên đó được xem là đã crawl được. `Bipolar disorder` thuộc trường
   hợp này.

## Kết quả theo từng job

| Job | Trạng thái | Parsed | Failed | Ghi chú |
| --- | --- | ---: | ---: | --- |
| `60269863...` | completed_with_errors | 38 | 1 | Artifact đã xóa; dữ liệu parsed không tạo URL duy nhất mới. |
| `5750c957...` | completed_with_errors | 0 | 39 | Coverage cũ đánh dấu lỗi; artifact đã xóa. |
| `856dfddc...` | completed_with_errors | 0 | 39 | Coverage cũ đánh dấu lỗi; artifact đã xóa. |
| `0633dcfa...` | completed | 39 | 0 | 25 tên yêu cầu; 21 matched, 4 not found. |
| `38692d40...` | completed | 23 | 0 | 25 tên yêu cầu; 18 matched, 7 not found. |
| `c5a63f00...` | completed_with_errors | 58 | 1 | Job nhiễu; chạm giới hạn 100 node, không cộng 23 URL chỉ có ở job này. |
| `ffb80fbb...` | completed | 37 | 0 | Chạy lại nhóm thứ ba; 25/25 tên matched. |
| `09d76b05...` | completed | 3 | 0 | 5 tên yêu cầu; 3 matched, 2 not found. |

Tổng số bản ghi parsed theo từng job là 198. Đây không phải số loại bệnh duy
nhất vì cùng một canonical URL có thể được crawl lại ở nhiều job.

## 13 tên đầu vào chưa crawl được

| STT | Tên đầu vào | Job audit | Trạng thái cuối |
| ---: | --- | --- | --- |
| 1 | Congenital heart disease | `0633dcfa...` | not_found |
| 2 | Overweight | `0633dcfa...` | not_found |
| 3 | Metabolic syndrome | `0633dcfa...` | not_found |
| 4 | Thyroid disorder | `0633dcfa...` | not_found |
| 5 | Elevated liver enzymes | `38692d40...` | not_found |
| 6 | Hepatic hemangioma | `38692d40...` | not_found |
| 7 | Liver cyst | `38692d40...` | not_found |
| 8 | Peptic ulcer disease | `38692d40...` | not_found |
| 9 | Gastroesophageal reflux disease / GERD | `38692d40...` | not_found |
| 10 | Gastric polyp | `38692d40...` | not_found |
| 11 | Colon polyp | `38692d40...` | not_found |
| 12 | Osteoarthritis | `09d76b05...` | not_found |
| 13 | Herniated disc / Disc herniation | `09d76b05...` | not_found |

`not_found` có nghĩa là pipeline không xác nhận được một disease detail phù hợp
với tên input; không có nghĩa là chắc chắn website nguồn không có nội dung đó.

## 99 loại bệnh đã crawl được

1. Alzheimer's disease
2. Aortic dilatation
3. Aortic valve stenosis
4. Asthma
5. Atrial fibrillation
6. Bariatric surgery
7. Bipolar disorder
8. Bronchiectasis
9. Brugada syndrome / Brugada pattern ECG
10. Cholecystitis
11. Cholelithiasis
12. Chronic glomerulonephritis
13. Chronic obstructive pulmonary disease
14. Chronic renal impairment
15. Coronary artery disease
16. Crohn disease
17. Diabetes mellitus
18. Diffuse parenchymal lung disease
19. Dilated cardiomyopathy
20. ECG changes
21. Ectopic beats
22. Epilepsy
23. Fatty liver
24. FH of Coronary artery disease
25. FH of Diabetes mellitus Type II
26. FH of Dilated cardiomyopathy
27. FH of Hypertrophic cardiomyopathy
28. FH of Pancreatic cancer
29. FH of Right ventricular arrhythmogenic cardiomyopathy
30. FH of Stroke
31. Focal segmental glomerulosclerosis
32. Functional cardiovascular symptoms
33. Gastritis
34. Gastrointestinal surgery
35. Generalized anxiety disorder
36. Glaucoma
37. Gout — có 2 canonical URL
38. Haematuria
39. Headache
40. Heart failure
41. Heart muscle diseases
42. Hepatitis B (residence in endemic areas)
43. Hepatitis B (residence in non-endemic areas)
44. Hepatitis C
45. Hyperlipoproteinaemia
46. Hypertension
47. Hyperthyroidism
48. Hypertrophic obstructive cardiomyopathy
49. Hypothyroidism
50. IgA nephropathy
51. Irritable bowel syndrome
52. Kidney stones
53. Left ventricular cardiomyopathy
54. Liver cirrhosis
55. Membranous glomerulonephritis
56. Mesenteric infarction
57. Mild depression
58. Mitral valve insufficiency
59. Moderate depression
60. Multiple and mixed valvular heart disease
61. Myocardial infarction
62. Nephrotic syndrome
63. Obesity
64. Osteoporosis
65. Pancreatic calcification
66. Pancreatitis
67. Parkinson disease
68. Paroxysmal supraventricular tachycardia
69. Phobic disorders
70. Pneumonia
71. Pneumothorax
72. Polycystic ovary syndrome
73. Portal hypertension
74. Post-streptococcal glomerulonephritis
75. Postcholecystectomy syndrome
76. Prostatic enlargement
77. Proteinuria
78. Pulmonary hypertension
79. Pulmonary nodules (applicants with high cancer risk)
80. Pulmonary nodules (applicants with low cancer risk)
81. Rapidly progressive nephritic syndrome
82. Renal cyst
83. Restrictive cardiomyopathy
84. Rheumatoid arthritis
85. Right ventricular arrhythmogenic cardiomyopathy
86. Severe depression
87. Sinus arrhythmia
88. Sleep apnoea
89. Stroke
90. Systemic lupus erythematosus
91. Takotsubo cardiomyopathy
92. Thrombolysis after myocardial infarction
93. Thyroid nodule
94. Transient ischaemic attack
95. Tuberculosis
96. Ulcerative colitis
97. Urinary tract infection
98. Ventricular fibrillation
99. Ventricular tachycardia

## 23 URL bị loại khỏi kết quả tin cậy

Các tên dưới đây chỉ xuất hiện trong job nhiễu `c5a63f00...` và không được một
job hoàn tất khác xác nhận lại bằng cùng canonical URL:

- Arthritis
- Atrioventricular block
- Autism spectrum disorders
- Bronchiectasis — canonical URL khác với trang Bronchiectasis đã được xác nhận
- Depressants, sedatives
- Effects of heat and light
- FH of Parkinson disease
- FH of Polycystic disease of the kidneys
- Gynaecomastia
- Kidney stones — canonical URL khác với trang Kidney stones đã được xác nhận
- Malaria
- Menstrual disorders
- Myeloproliferative disorders
- Partial or total absence of limb(s)
- Polycystic disease of kidney
- Pre-excitation syndrome
- Retinal vein occlusion
- Schizophrenia
- Thyroidectomy
- Tubulo-interstitial nephritis
- Typhus fever
- Urinary incontinence
- Weight loss

Các URL này không nhất thiết là nội dung sai trên website. Chúng bị loại vì
không có bằng chứng rằng chúng liên quan đúng đến danh sách input của job thứ
ba sau sự cố autocomplete.

## Khuyến nghị chạy tiếp

Tạo một job import riêng cho 13 tên chưa tìm thấy, mỗi lần 5–10 tên. Giữ mở
rộng category nhưng kiểm tra `import-search.json` ngay sau discovery. Chỉ chuyển
sang fetch khi từng tên gốc có candidate hợp lý; không tăng node limit nếu queue
chứa kết quả không liên quan.
