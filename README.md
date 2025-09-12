# 🏭 Production Management System

A comprehensive Flask-based production management system for garment manufacturing with barcode scanning, worker tracking, and real-time production monitoring.

## ✨ Features

### 🔧 Core Functionality
- **Worker Management**: Add workers with unique QR codes for authentication
- **File Upload System**: Upload OB files (Operations Breakdown) and Production Orders
- **Bundle Generation**: Automatically create 12 bundles per production order
- **Production Tracking**: Real-time tracking of pieces completed and earnings
- **ESP32 Integration**: Barcode/QR scanning support for hardware devices

### 📊 Analytics & Reporting
- **Live Dashboard**: Real-time production statistics and metrics
- **Worker Performance**: Track individual worker productivity and earnings
- **Bundle Management**: Monitor bundle status and completion rates
- **Export Capabilities**: Generate Excel reports for data analysis

### 🎨 Modern Interface
- **Responsive Design**: Works perfectly on desktop, tablet, and mobile
- **Dark Theme**: Professional glassmorphism design with modern aesthetics
- **Real-time Updates**: Live data refresh every 30 seconds
- **Intuitive Navigation**: Easy-to-use sidebar navigation with mobile support

## 🚀 Quick Start

### Local Development

1. **Clone and Setup**
   ```bash
   # Extract the ZIP file and navigate to directory
   cd production_management_system

   # Create virtual environment
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate

   # Install dependencies
   pip install -r requirements.txt
   ```

2. **Run the Application**
   ```bash
   python app.py
   ```

   Open http://localhost:5000 to access the system

### 🌐 Deploy on Render

1. **Upload to GitHub**
   - Create a new GitHub repository
   - Upload all project files to the repository

2. **Deploy on Render**
   - Go to [Render.com](https://render.com) and sign in
   - Click "New" → "Web Service"
   - Connect your GitHub repository
   - Configure deployment:
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn app:app`
     - **Environment**: Python 3

3. **Environment Variables** (Optional - Set in Render dashboard)
   ```
   SECRET_KEY=your-production-secret-key
   DATABASE_URL=your-postgresql-url  # Render will provide this
   ```

## 📁 Project Structure

```
production_management_system/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── Procfile              # Deployment configuration
├── runtime.txt           # Python version
├── README.md             # This file
├── static/
│   ├── style.css         # Main stylesheet
│   ├── app.js           # Frontend JavaScript
│   └── qrcodes/         # Generated QR codes
├── templates/
│   ├── layout.html      # Base template
│   ├── dashboard.html   # Dashboard page
│   ├── workers.html     # Workers management
│   ├── production.html  # File upload page
│   ├── bundles.html     # Bundle management
│   ├── operations.html  # Operations management
│   └── reports.html     # Reports and analytics
└── uploads/             # File upload directory
```

## 🗄️ Database Schema

### Tables
- **workers**: Worker information and QR codes
- **operations**: Production operations with piece rates
- **production_orders**: Style and quantity information
- **ob_files**: Uploaded OB file history
- **bundles**: Generated production bundles
- **worker_bundles**: Worker-bundle assignments and progress
- **logs**: Worker activity logs

## 🔌 ESP32 Integration

### Scan Endpoint: `POST /scan`

```json
{
  "token_id": "W:WORKER123",
  "action": "login"
}
```

### Response Format
```json
{
  "success": true,
  "message": "Worker John Smith login successful",
  "worker": {
    "id": 1,
    "name": "John Smith",
    "department": "Cutting",
    "line": "Line-1"
  }
}
```

## 📤 File Upload Formats

### OB File (Operations Breakdown)
Excel/CSV file with columns:
- `SeqNo`: Operation sequence number
- `OpNo`: Operation number
- `Description`: Operation description
- `Machine`: Machine type
- `SubSection`: Department/section
- `StdMin`: Standard minutes per piece

### Production Order File
Excel/CSV file with columns:
- `Order No`: Production order number
- `Style Number`: Garment style number
- `Style Name`: Style description
- `Buyer`: Customer name
- `Total Quantity`: Total pieces to produce

## 🎯 Usage Workflow

1. **Setup Workers**: Add workers with unique Token IDs and generate QR codes
2. **Upload Files**: Upload OB file and Production Order files
3. **Auto-Generate**: System creates 12 bundles per production order
4. **Assign Work**: Assign bundles to workers with specific operations
5. **Track Progress**: Monitor real-time production and earnings
6. **Generate Reports**: Export worker productivity and earnings data

## 🛠️ API Endpoints

### Dashboard API
- `GET /api/dashboard_stats` - Live dashboard statistics

### ESP32 Integration
- `POST /scan` - Barcode/QR scanning endpoint

### File Management
- `POST /upload_ob_file` - Upload operations breakdown file
- `POST /upload_production_order` - Upload production order file

### Worker Management
- `POST /add_worker` - Add new worker
- `GET /worker/<id>/qr` - Get worker QR code
- `GET /toggle_worker/<id>` - Toggle worker status

## 🔒 Security Features

- Secure file upload validation
- Database input sanitization
- CSRF protection for forms
- Environment-based configuration

## 📈 System Capabilities

- Handle unlimited operations from Excel files
- Process production orders with multiple colors/sizes
- Track worker productivity with piece-rate earnings
- Generate QR codes for ESP32 scanning
- Export data to Excel for analysis
- Real-time dashboard updates
- Multi-line production management

## 🚨 Troubleshooting

### Common Issues

1. **Database Connection Error**
   - Ensure database is accessible
   - Check DATABASE_URL environment variable

2. **File Upload Issues**
   - Check file size (max 16MB)
   - Verify file format (Excel/CSV only)
   - Ensure upload directory permissions

3. **QR Code Generation Failed**
   - Check static/qrcodes directory permissions
   - Verify segno package installation

## 📄 License

This project is designed for internal use in garment manufacturing operations.

---

**Built for modern garment manufacturing operations** 🏭
