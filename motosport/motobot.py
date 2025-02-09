import os
import time
import csv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException
from motosport.constants import news_sites  # Import news URLs

class MotoBot(webdriver.Chrome):
    def __init__(self, driver_path=r"C:/SeleniumDrivers"):
        """
        Initializes the WebDriver and sets up paths.
        """
        self.driver_path = driver_path
        os.environ['PATH'] += os.pathsep + self.driver_path  # Ensure correct path formatting
        super(MotoBot, self).__init__()




    def get_webpages(self):
        """Opens each news website in the list."""
        for site, info in news_sites.items():
            self.get(info["url"])
            time.sleep(5)  # Wait for the page to load




    def privacy_notation(self):
        """Handles cookie/privacy pop-ups if present."""
        buttons = self.find_elements(By.XPATH, "//button[@id='onetrust-accept-btn-handler']")
        if buttons:
            time.sleep(2)
            buttons[0].click()




    def headline_scrape(self, max_retries=3):
        """Scrapes headlines and handles stale element exceptions."""
        retries = 0
        while retries < max_retries:
            try:
                headlines = self.find_elements(By.CSS_SELECTOR, "h2")
                return [element.text for element in headlines if element.text.strip()]  # Avoid empty headlines
            except StaleElementReferenceException:
                retries += 1
                print(f"Retrying headline scrape ({retries}/{max_retries}) due to stale elements...")
                time.sleep(2)  # Short delay before retrying
        print("Failed to retrieve headlines after retries.")
        return []




    def save_csv(self, headline_data, filename="news_headlines.csv"):
        """Saves headlines to a CSV file."""
        with open(filename, "w", newline="", encoding="utf-8") as file:
            csvwriter = csv.writer(file)
            csvwriter.writerow(["Headline"])  # Column header
            csvwriter.writerows([[headline] for headline in headline_data])  # Ensure correct format
        print(f"Headlines saved to {filename}")




    def run(self):
        """Main execution function."""
        try:
            self.get_webpages()
            self.privacy_notation()
            headlines = self.headline_scrape()
            if headlines:
                self.save_csv(headlines)
            else:
                print("No headlines found.")
        finally:
            time.sleep(2)
            self.quit()  # Ensure browser closes

# Usage
if __name__ == "__main__":
    bot = MotoBot()
    bot.run()

#Below was some testing about the element of the Accept button
#class Accept(webdriver.Chrome):

    #def btn_clicker(self):
        #accept_button = self.find_element(By.XPATH, "//button[@id='onetrust-accept-btn-handler']")

        #time.sleep(5)
        #accept_button.click()

    #def run2(self):
        #self.get("https://www.espn.com/racing/")
        #time.sleep(3)
        #self.btn_clicker()
