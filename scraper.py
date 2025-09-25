import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime, timedelta

URL = "https://mtolympusgym.us/pages/weekly-schedule"

def fetch_closed_times():
    r = requests.get(URL)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    closed_times = []

    # Example: look for <td> with inline style "color:red" or similar
    for cell in soup.find_all("td"):
        style = cell.get("style", "").lower()
        if "red" in style:  # this is simplistic; adjust based on site
            text = cell.get_text(strip=True)
            day = cell.find_parent("tr").find("td").get_text(strip=True)
            closed_times.append((day, text))

    return closed_times


def parse_time_range(day, time_str):
    """
    Convert something like '5:00 PM - 7:00 PM' to datetime ranges.
    Assumes current week.
    """
    import dateutil.parser
    import datetime as dt

    # get "this week's" Monday as baseline
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())

    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_index = weekdays.index(day.lower())

    event_date = monday + dt.timedelta(days=day_index)

    start_str, end_str = [s.strip() for s in time_str.split("-")]
    start_dt = dateutil.parser.parse(start_str).replace(
        year=event_date.year, month=event_date.month, day=event_date.day
    )
    end_dt = dateutil.parser.parse(end_str).replace(
        year=event_date.year, month=event_date.month, day=event_date.day
    )

    return start_dt, end_dt


def build_calendar(events):
    cal = Calendar()
    for day, times in events:
        try:
            start, end = parse_time_range(day, times)
        except Exception as e:
            print("Skipping", day, times, e)
            continue
        e = Event()
        e.name = "Gym Closed"
        e.begin = start
        e.end = end
        cal.events.add(e)
    return cal


if __name__ == "__main__":
    closed = fetch_closed_times()
    cal = build_calendar(closed)
    with open("gym-closed.ics", "w") as f:
        f.writelines(cal)
    print("Generated gym-closed.ics")

