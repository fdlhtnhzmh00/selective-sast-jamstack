# Jamstack CI/CD Selective-SAST Dataset & Scripts

Repository ini berisi dataset primer dan skrip analitik untuk penelitian DevSecOps terkait optimasi waktu eksekusi CI/CD pipeline pada arsitektur Jamstack menggunakan pendekatan *Selective-SAST* berbasis analisis *Code Churn*.

## 📊 Isi Repository
- `data/`: Berisi dataset final (`final_dataset_patched.csv`) yang mencakup 2.450 commit unik dari 49 repositori Jamstack.
- `scripts/`: Skrip Python (termasuk PyDriller) untuk mengekstraksi riwayat commit dan metrik churn.
- `notebooks/`: File eksplorasi data (Jupyter Notebook) untuk pengujian Spearman's Rank Correlation dan pembuatan grafik.
- `config/`: Parameter konfigurasi eksperimen.

## 📝 Sitasi (Citation)
Dataset dan metodologi dalam repositori ini telah dipublikasikan secara resmi. Jika Anda menggunakan data ini untuk keperluan akademis atau riset, mohon mengutip artikel berikut:

> **Hazimah, F. T., dkk. (2026). "CI/CD Pipeline Execution Time Optimization Using Code Churn-Based Selective-SAST on Jamstack Architecture."** *Journal of Informatics Unisla (JOUTICA)*, 11(2), 241-256. DOI: [10.30736/jti.v11i2.1695](https://jurnalteknik.unisla.ac.id/index.php/informatika/article/view/1695)

## ⚙️ Cara Penggunaan
Install dependensi yang dibutuhkan dengan perintah:
```bash
pip install -r requirements.txt