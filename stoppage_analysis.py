import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from datetime import timedelta
import movingpandas as mpd
import folium

# --- Configuration ---
# IMPORTANT: Replace 'google_sheets_service_account.json' with the actual
# path to your downloaded JSON key file relative to your script.
# If it's in a subfolder named 'credentials', it would be 'credentials/google_sheets_service_account.json'
SERVICE_ACCOUNT_FILE = 'google_sheets_service_account.json'

# Your Google Sheet URL (the one you provided)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1Lro5MJbxHtbjEg4TLuO6qTs5sPYL6DmqbQNJOEtiGPQ/edit?usp=sharing"

# User-defined stoppage threshold in minutes
STOPPAGE_THRESHOLD_MINUTES = 5

# --- Step 1: Authenticate and Load Data from Google Sheet ---
print("Attempting to load data from Google Sheet...")
try:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)

    sheet = client.open_by_url(SHEET_URL).sheet1
    data = sheet.get_all_values()

    df = pd.DataFrame(data[1:], columns=data[0])
    print("Data loaded successfully from Google Sheet.")
    print("Columns loaded:", df.columns.tolist()) # ADD THIS LINE
    print("Initial DataFrame head:\n", df.head()) # UNCOMMENT THIS LINE

except Exception as e:
    print(f"Error loading data from Google Sheet: {e}")
    print("Please ensure:")
    print(f"1. Your SERVICE_ACCOUNT_FILE path ('{SERVICE_ACCOUNT_FILE}') is correct.")
    print("2. The Google Sheet is shared with the service account email (found in your JSON key file, like: niru-154@empyrean-cursor-466407-c5.iam.gserviceaccount.com).")
    exit()

# --- Step 2: Prepare Data for MovingPandas ---
print("\nPreparing GeoDataFrame...")
try:
    # Use 'eventGeneratedTime' as the primary timestamp column
    # Convert Unix milliseconds timestamp to datetime
    df['eventGeneratedTime'] = pd.to_numeric(df['eventGeneratedTime'], errors='coerce')
    df['Timestamp'] = pd.to_datetime(df['eventGeneratedTime'], unit='ms', errors='coerce')

    print("DEBUG: Timestamp column head after creation:\n", df['Timestamp'].head())
    print("DEBUG: Number of NaT values in Timestamp column:", df['Timestamp'].isna().sum())

    # Set 'Timestamp' as the index
    print("DEBUG: Attempting to set 'Timestamp' as index...")
    df = df.set_index('Timestamp').sort_index()
    print("DEBUG: 'Timestamp' successfully set as index.")
    print("DEBUG: DataFrame head after set_index:\n", df.head())

    # Convert 'latitude' and 'longitude' to numeric types
    print("DEBUG: Converting latitude to numeric...")
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    print("DEBUG: Converting longitude to numeric...")
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')

    print("DEBUG: Number of NaN values in latitude column:", df['latitude'].isna().sum()) # ADD THIS
    print("DEBUG: Number of NaN values in longitude column:", df['longitude'].isna().sum()) # ADD THIS

    # Drop rows with NaN values in Timestamp, latitude or longitude (if any conversion failed)
    print("DEBUG: Attempting to drop NaNs from Timestamp, latitude, longitude subset...")
    df.dropna(subset=['latitude', 'longitude'], inplace=True) # REMOVED 'Timestamp' from subset
    print("DEBUG: NaNs dropped successfully.") # This line won't be reached if error is on dropna
    print("DEBUG: DataFrame shape after dropping NaNs:", df.shape)
    print("DEBUG: Is DataFrame empty after dropping NaNs?", df.empty)


    # Create a 'geometry' column
    df['geometry'] = [Point(xy) for xy in zip(df['longitude'], df['latitude'])]

    # Create a GeoDataFrame
    gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
    print("GeoDataFrame created successfully.")
    # print("GeoDataFrame head:\n", gdf.head()) # Uncomment to see GeoDataFrame head

except Exception as e:
    print(f"Error preparing GeoDataFrame: {e}")
    exit()
    # --- Step 3: Identify Stoppage Events ---
print(f"\nDetecting stoppages with a threshold of {STOPPAGE_THRESHOLD_MINUTES} minutes...")
try:
    if gdf.empty:
        print("No valid GPS data points to create a trajectory. Exiting.")
        stop_points = gpd.GeoDataFrame(columns=['start_time', 'end_time', 'duration_minutes', 'geometry'], crs="EPSG:4326")
    else:
        # Assuming 'EquipmentId' can be used as the trajectory ID if it exists, otherwise use a generic ID
        trajectory_id_col = 'EquipmentId' if 'EquipmentId' in gdf.columns else 'Vehicle1_ID'
        trajectory = mpd.Trajectory(gdf, trajectory_id_col)

        min_duration_td = timedelta(minutes=STOPPAGE_THRESHOLD_MINUTES)
        max_diameter_meters = 50 # Max distance (in meters) considered stationary due to GPS inaccuracies

        detector = mpd.TrajectoryStopDetector(trajectory)
        stop_points = detector.get_stop_points(min_duration=min_duration_td, max_diameter=max_diameter_meters)

        # ADD THESE DEBUG PRINTS HERE:
        print("DEBUG: stop_points created. Is it empty?", stop_points.empty)
        if not stop_points.empty:
            print("DEBUG: stop_points columns:", stop_points.columns.tolist())
            print("DEBUG: stop_points head:\n", stop_points.head())
        # END OF DEBUG PRINTS

        if not stop_points.empty:
            stop_points['duration_minutes'] = stop_points['duration_s'] / 60 # Corrected column name and removed .dt.total_seconds()
            print(f"{len(stop_points)} stoppage(s) identified.")
            print("Stoppage Points (first 5):\n", stop_points[['start_time', 'end_time', 'duration_minutes']].head())
        else:
            print("No stoppages found exceeding the defined threshold.")

except Exception as e:
    print(f"Error detecting stoppages: {e}")
    exit()

# --- Step 4: Visualize on an Interactive Map (using Folium) ---
print("\nCreating interactive map...")
try:
    if not gdf.empty:
        map_center_lat = gdf['latitude'].mean() # Changed from 'Latitude'
        map_center_lon = gdf['longitude'].mean() # Changed from 'Longitude'
    else:
        # Default to a location near Borkhedi, Maharashtra, India if no data
        map_center_lat = 20.0827
        map_center_lon = 78.9629

    m = folium.Map(location=[map_center_lat, map_center_lon], zoom_start=12)

    # Add the entire vehicle path to the map
    if not gdf.empty:
        path_coords = list(zip(gdf['latitude'], gdf['longitude'])) # Changed from 'Latitude' / 'Longitude'
        folium.PolyLine(
            locations=path_coords,
            color="blue",
            weight=3,
            opacity=0.7,
            tooltip="Vehicle Path"
        ).add_to(m)
        print("Vehicle path added to map.")

    # Add markers for each identified stoppage
    if not stop_points.empty:
        for idx, row in stop_points.iterrows():
            reach_time_str = row['start_time'].strftime('%Y-%m-%d %H:%M:%S')
            end_time_str = row['end_time'].strftime('%Y-%m-%d %H:%M:%S')
            stoppage_duration_minutes = round(row['duration_minutes'], 2)

            popup_html = f"""
            <b>Stoppage Details</b><br>
            -----------------------------<br>
            <b>Reach Time:</b> {reach_time_str}<br>
            <b>End Time:</b> {end_time_str}<br>
            <b>Duration:</b> {stoppage_duration_minutes} minutes
            """

            folium.Marker(
                location=[row.geometry.y, row.geometry.x],
                popup=folium.Popup(popup_html, max_width=300),
                icon=folium.Icon(color="red", icon="info-sign")
            ).add_to(m)
        print(f"{len(stop_points)} stoppage markers added to map.")
    else:
        print("No stoppage markers to add to map.")

    # --- Save the map to an HTML file ---
    output_map_file = "vehicle_stoppages_map.html"
    m.save(output_map_file)
    print(f"\nMap saved successfully to '{output_map_file}'.")
    print("Open this file in your web browser to view the visualization.")

except Exception as e:
    print(f"Error during map visualization: {e}")