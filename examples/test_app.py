import sys
try:
    from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    print("Please install PyQt6 and PyQt6-WebEngine.")
    sys.exit(1)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QtWebEngine Test App")
        self.resize(800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        self.web_view = QWebEngineView()
        self.web_view.setHtml("""
        <html>
            <head>
                <title>Test Page</title>
                <style>
                    body { font-family: Arial, sans-serif; padding: 40px; background: #f5f5f5; }
                    h1 { color: #333; }
                    #counter { font-size: 48px; font-weight: bold; color: #0066cc; margin: 20px 0; }
                    #incrementButton {
                        font-size: 20px; padding: 12px 32px; cursor: pointer;
                        background: #0066cc; color: white; border: none; border-radius: 8px;
                    }
                    #incrementButton:hover { background: #0052a3; }
                    .status { margin-top: 20px; color: #666; }
                </style>
            </head>
            <body>
                <h1>Hello, QtWebEngine!</h1>
                <p>This is a test application for Antigravity desktop testing.</p>
                <div>Counter: <span id="counter">0</span></div>
                <button id="incrementButton" onclick="increment()">Increment</button>
                <p class="status" id="status">Ready</p>
                <script>
                    var count = 0;
                    function increment() {
                        count++;
                        document.getElementById('counter').textContent = count;
                        document.getElementById('status').textContent = 'Counter updated to ' + count;
                    }
                </script>
            </body>
        </html>
        """)
        
        layout.addWidget(self.web_view)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
