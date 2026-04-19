import sys
import os
import random
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from PyQt5.QtCore import *

class Star:
    """Represents a single star in the starfield"""
    def __init__(self, x, y, size, brightness, speed, color):
        self.x = x
        self.y = y
        self.size = size
        self.brightness = brightness
        self.original_brightness = brightness
        self.speed = speed
        self.color = color
        self.twinkle_direction = 1  # 1 for brightening, -1 for dimming
        self.twinkle_speed = random.uniform(0.005, 0.02)
        self.layer = random.randint(1, 3)  # Parallax layers

class StarfieldWidget(QWidget):
    """Interactive starfield widget with mouse gesture support"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.stars = []
        self.mouse_x = 0
        self.mouse_y = 0
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.animate_stars)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        
        # Set widget properties for overlay
        self.setStyleSheet("background-color: black;")
        self.setAutoFillBackground(True)
        
        # For fade in/out effect
        self.opacity = 0.0
        self.fade_direction = 1  # 1 for fading in, -1 for fading out
        
        # Initialize stars
        self.initialize_stars()
        
    def initialize_stars(self):
        """Create random stars with varying properties"""
        screen = QApplication.primaryScreen().geometry()
        star_count = int((screen.width() * screen.height()) / 1000)  # Adjust density based on screen size
        
        for _ in range(star_count):
            # Position stars randomly across the screen
            x = random.randint(0, screen.width())
            y = random.randint(0, screen.height())
            
            # Size between 1-3 pixels
            size = random.randint(1, 3)
            
            # Brightness between 50-255
            brightness = random.randint(50, 255)
            
            # Speed for parallax effect (closer stars move faster)
            speed = random.uniform(0.05, 0.2)
            
            # Color variations for visual interest
            if random.random() < 0.8:
                # Most stars are white
                color = QColor(255, 255, 255, brightness)
            elif random.random() < 0.9:
                # Some blue stars
                color = QColor(200, 200, 255, brightness)
            else:
                # Occasional other colors for interest
                color = QColor(255, 200, 200, brightness)  # Reddish
                
            self.stars.append(Star(x, y, size, brightness, speed, color))
            
    def paintEvent(self, event):
        """Draw all stars with their current properties"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw a dark background with adjusted color for deeper space effect
        background_color = QColor(5, 5, 25, int(200 * self.opacity))
        painter.fillRect(self.rect(), background_color)
        
        # Draw each star with opacity
        for star in self.stars:
            # Calculate parallax effect based on mouse position and star layer
            parallax_x = (self.mouse_x - self.width() / 2) * star.speed * star.layer * 0.01
            parallax_y = (self.mouse_y - self.height() / 2) * star.speed * star.layer * 0.01
            
            # Apply parallax effect
            x = star.x + parallax_x
            y = star.y + parallax_y
            
            # Wrap stars around screen edges
            x = x % self.width()
            y = y % self.height()
            
            # Set star color with current brightness and widget opacity
            color = star.color
            color.setAlpha(int(star.brightness * self.opacity))
            painter.setPen(QPen(color))
            painter.setBrush(QBrush(color))
            
            # Draw star
            painter.drawEllipse(int(x), int(y), star.size, star.size)
            
        painter.end()
        
    def mouseMoveEvent(self, event):
        """Update mouse position for parallax effect"""
        self.mouse_x = event.x()
        self.mouse_y = event.y()
        self.update()  # Trigger repaint
        
    def animate_stars(self):
        """Update star properties for twinkling effect"""
        # Update fade effect
        self.opacity += 0.02 * self.fade_direction
        if self.opacity >= 1.0:
            self.opacity = 1.0
            self.fade_direction = -1 if self.fade_direction == 1 else self.fade_direction
        elif self.opacity <= 0.0 and self.fade_direction == -1:
            self.opacity = 0.0
            # Stop animation when fully faded out
            if self.isHidden():
                self.animation_timer.stop()
                
        # Update twinkling effect with slower, more gentle animation
        for star in self.stars:
            # Slower twinkling for calming effect
            star.brightness += star.twinkle_speed * star.twinkle_direction * 5
            
            # Reverse direction if brightness goes out of bounds
            if star.brightness > 255:
                star.brightness = 255
                star.twinkle_direction = -1
            elif star.brightness < star.original_brightness * 0.5:
                star.brightness = star.original_brightness * 0.5
                star.twinkle_direction = 1
                
            # Very rarely create shooting stars for special effect
            if random.random() < 0.00005 and star.layer == 3:  # Extremely rare
                self.create_shooting_star(star)
                
        self.update()  # Trigger repaint
        
    def create_shooting_star(self, star):
        """Create a shooting star effect"""
        # For now, just brighten the star significantly
        star.brightness = 255
        star.twinkle_direction = -1  # Start dimming immediately
        
    def showEvent(self, event):
        """Start animation when widget is shown"""
        super().showEvent(event)
        if event.type() == QEvent.Show:
            self.fade_direction = 1  # Fade in
            self.animation_timer.start(100)  # Slower animation for calming effect (10 FPS)
            
    def hideEvent(self, event):
        """Start fade out when widget is hidden"""
        super().hideEvent(event)
        if event.type() == QEvent.Hide:
            self.fade_direction = -1  # Fade out
            # Don't stop the timer here, let the animate_stars method handle it
            # This ensures a smooth fade out effect