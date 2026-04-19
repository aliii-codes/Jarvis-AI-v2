import sys 
import requests
from dotenv import dotenv_values

env_vars = dotenv_values(".env")


def getweather():
    city = input("Enter Your City: ")
    if city:
        api = env_vars.get("WeatherAPIKey")
        url = f'http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api}&units=metric'
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            name = data['name']
            country = data['sys']['country']
            weather_description = data['weather'][0]['description']
            temperature = data['main']['temp']
            feels_like = data['main']['feels_like']
            humidity = data['main']['humidity']
            wind_speed = data['wind']['speed']

            print(f"\nWeather in {name}, {country}")
            print(f"Condition: {weather_description.capitalize()}")
            print(f"Temperature: {temperature}°C")
            print(f"Feels Like: {feels_like}°C")
            print(f"Humidity: {humidity}%")
            print(f"Wind Speed: {wind_speed} m/s")
        else:
            print("Error:", response.status_code)
    else:
        print("No city provided")




if __name__ == "__main__":
    getweather()
    