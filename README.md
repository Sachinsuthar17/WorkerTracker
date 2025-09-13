# 🏭 Production Dashboard - Complete Multi-Page Application

A modern, dark-themed production tracking dashboard with full CRUD functionality for workers, operations, and production logging.

## ✨ Features

### 📊 Dashboard
- Real-time production statistics
- Interactive Chart.js visualizations
- Live activity feed
- Modern dark theme UI

### 👥 Workers Management
- Add new workers with departments
- View all workers in a formatted table
- Track worker status and creation dates

### ⚙️ Operations Management
- Define operation types (Cutting, Sewing, etc.)
- Add descriptions for each operation
- Manage production workflow steps

### 📈 Production Logging
- Log production entries by worker and operation
- Track quantities and timestamps
- View recent production history

### 📋 Reports
- Export production data as CSV
- Download complete production logs
- Worker and operation analytics

### 🔧 Settings
- System configuration (placeholder)
- Notification preferences
- Database status monitoring

## 🚀 Quick Start

### Local Development
```bash
# Clone and setup
git clone <your-repo>
cd production-dashboard

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py

# Visit http://localhost:10000
```

### Deploy to Render (Free!)
1. Push code to GitHub
2. Connect repository to Render
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `gunicorn app:app`
5. Deploy and get your live URL!

## 📁 Project Structure
```
production-dashboard/
├── app.py                 # Flask backend with all routes
├── requirements.txt       # Python dependencies
├── Procfile              # Render deployment config
├── templates/
│   ├── layout.html       # Base template with sidebar
│   ├── dashboard.html    # Dashboard with charts
│   ├── workers.html      # Workers management
│   ├── operations.html   # Operations management
│   ├── production.html   # Production logging
│   ├── reports.html      # Reports and exports
│   └── settings.html     # Settings page
└── static/
    ├── style.css         # Modern dark theme styles
    └── app.js            # Interactive JavaScript
```

## 🎨 Design Features
- **Modern Dark Theme**: Professional gradient backgrounds
- **Glassmorphism Effects**: Subtle blur and transparency
- **Responsive Layout**: Works on desktop, tablet, and mobile
- **Interactive Charts**: Chart.js with smooth animations
- **Live Updates**: Real-time data refresh every 30 seconds

## 🛠️ Technology Stack
- **Backend**: Flask, SQLite
- **Frontend**: HTML5, CSS3, JavaScript
- **Charts**: Chart.js
- **Icons**: Font Awesome
- **Deployment**: Gunicorn, Render

## 📊 Database Schema
- **workers**: id, name, department, status, created_at
- **operations**: id, name, description, created_at
- **production_logs**: id, worker_id, operation_id, quantity, timestamp, status

## 🔧 API Endpoints
- `GET /` - Dashboard
- `GET /workers` - Workers management
- `GET /operations` - Operations management
- `GET /production` - Production logging
- `GET /reports` - Reports page
- `GET /settings` - Settings page
- `GET /api/stats` - Production statistics
- `GET /api/chart-data` - Chart data
- `GET /download_report` - CSV export

## 📱 Mobile Support
- Responsive design with mobile-first approach
- Collapsible sidebar navigation
- Touch-friendly forms and buttons
- Optimized for mobile screens

## 🚀 Deployment Options
- **Render.com** (Free tier available)
- **Heroku** (With Procfile included)
- **DigitalOcean App Platform**
- **Local development server**

## 🤝 Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License
MIT License - Open source and free to use

---
**Built with ❤️ for modern production tracking**
