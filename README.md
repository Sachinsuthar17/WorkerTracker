# 🏭 Production Dashboard System

A complete production tracking system with barcode scanning, worker management, and real-time analytics.

## ✨ Features

- **Workers Management**: Add workers with QR codes for login
- **Operations Tracking**: Define and track different production operations  
- **Real-time Dashboard**: Live production statistics and activity feed
- **Barcode Scanning**: ESP32 integration for barcode/QR scanning
- **Production Logging**: Manual and automatic production entry logging
- **Data Export**: CSV exports for reports and analytics
- **Modern UI**: Dark theme with responsive design

## 🚀 Quick Start

### Local Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python start_server.py

# Open browser to http://localhost:5000
```

### ESP32 Integration
The system provides a unified `/scan` endpoint for ESP32 devices:

```json
POST /scan
{
    "secret": "your_device_secret",
    "token_id": "W:WORKER123",
    "barcode": "B:OP10-BATCH001"
}
```

## 📊 Database Schema

- **workers**: User accounts with QR tokens
- **operations**: Production operation definitions
- **scans**: Barcode scan records
- **production_logs**: Manual production entries
- **app_state**: Current active worker session

## 🎯 Usage

1. **Add Workers**: Create worker accounts with unique tokens
2. **Define Operations**: Set up your production operations (Cutting, Sewing, etc.)
3. **Scan QR Codes**: Workers scan their QR to login/logout
4. **Scan Barcodes**: Scan product barcodes to track production
5. **View Dashboard**: Monitor real-time statistics
6. **Export Data**: Download CSV reports

## 🔧 Configuration

Set environment variables:
- `APP_BRAND`: Application name
- `DEVICE_SECRET`: ESP32 authentication secret
- `RATE_PER_PIECE`: Earnings per piece (default: 2.00)
- `FLASK_SECRET`: Session secret

## 📱 Mobile Support

The interface is fully responsive and works on mobile devices.

## 🔄 API Endpoints

- `GET /api/stats` - Current statistics
- `GET /api/activities` - Recent activities  
- `POST /scan` - ESP32 barcode scanning
- `GET /workers/{id}/qr.png` - Worker QR codes

Built with Flask, SQLite, and modern web technologies.
