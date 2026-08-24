import sys
import os

try:
    from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    print("Please install PyQt6 and PyQt6-WebEngine.")
    sys.exit(1)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal Webview Counter - QtWebEngine")
        self.resize(800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        self.web_view = QWebEngineView()
        self.web_view.setHtml("""
        <!DOCTYPE html>
        <html>
            <head>
                <title>Universal Webview Counter</title>
                <style>
                    body { font-family: Arial, sans-serif; padding: 40px; background: #f5f5f5; text-align: center; }
                    h1 { color: #333; }
                    #counter { font-size: 48px; font-weight: bold; color: #0066cc; margin: 20px 0; }
                    button {
                        font-size: 20px; padding: 12px 32px; cursor: pointer;
                        background: #0066cc; color: white; border: none; border-radius: 8px;
                    }
                    button:hover { background: #0052a3; }
                    #status { margin-top: 20px; color: #666; font-size: 16px; }
                </style>
            </head>
            <body>
                <h1>Universal Desktop Webview</h1>
                <div>Counter: <span id="counter">0</span></div>
                <button id="increment-btn" onclick="increment()">Increment</button>
                <button id="incrementButton" onclick="increment()" style="display:none">Increment</button>
                <p id="status">Ready</p>
                <script>
                    var count = 0;
                    function increment() {
                        count++;
                        document.getElementById('counter').textContent = count.toString();
                        document.getElementById('status').textContent = 'Clicked: ' + count;
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
