# Distance/Main.py
"""
Main entry point for the Distance Calibration System.
Provides a calibration manager for creating, listing, and testing calibrations.
"""

import sys
import os

# Adjust the Python path to include the root directory of the project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Distance.Storage import (
    list_calibrations, get_calibration, get_calibration_points,
    delete_calibration, get_test_results, get_detection_coverage
)
from Distance.Model import load_model
from Distance.Calibration import run_video_calibration, run_legacy_calibration
from Distance.Test import run_video_test, test_model_live, run_detection_coverage_analysis


def print_header():
    """Print the application header."""
    print("\n" + "="*60)
    print("   DISTANCE CALIBRATION MANAGER")
    print("="*60)


def print_menu():
    """Print the main menu."""
    print("\nOptions:")
    print("  [1] List all calibrations")
    print("  [2] Create new video calibration")
    print("  [3] Create new live camera calibration (legacy)")
    print("  [4] Test a calibration (video)")
    print("  [5] Test a calibration (live camera)")
    print("  [6] View calibration details")
    print("  [7] View test results")
    print("  [8] Delete a calibration")
    print("  [9] Analyze detection coverage (video)")
    print("  [Q] Quit")
    print("-"*40)


def list_all_calibrations():
    """List all available calibrations."""
    calibrations = list_calibrations()
    
    print("\n" + "-"*60)
    print("AVAILABLE CALIBRATIONS")
    print("-"*60)
    
    if not calibrations:
        print("No calibrations found.")
        print("Use option [2] or [3] to create a new calibration.")
    else:
        print(f"{'#':<4} {'Name':<20} {'Zoom':<10} {'Points':<8} {'Type':<12}")
        print("-"*60)
        for i, cal in enumerate(calibrations, 1):
            print(f"{i:<4} {cal['name']:<20} {cal['zoom_label']:<10} "
                  f"{cal['num_points']:<8} {cal['source_type']:<12}")
    
    print("-"*60)
    return calibrations


def select_calibration(prompt="Select calibration number"):
    """Helper to select a calibration from the list."""
    calibrations = list_all_calibrations()
    
    if not calibrations:
        return None
    
    try:
        choice = int(input(f"\n{prompt} (0 to cancel): ").strip())
        if choice == 0:
            return None
        if 1 <= choice <= len(calibrations):
            return calibrations[choice - 1]["name"]
        print("Invalid selection.")
        return None
    except ValueError:
        print("Invalid input.")
        return None


def view_calibration_details():
    """View detailed information about a calibration."""
    cal_name = select_calibration("Select calibration to view")
    if not cal_name:
        return
    
    cal = get_calibration(cal_name)
    if not cal:
        print(f"Calibration '{cal_name}' not found.")
        return
    
    print("\n" + "="*60)
    print(f"CALIBRATION: {cal_name}")
    print("="*60)
    
    print("\nMetadata:")
    metadata = cal.get("metadata", {})
    print(f"  Source Type: {metadata.get('source_type', 'unknown')}")
    print(f"  Source Path: {metadata.get('source_path', 'N/A')}")
    print(f"  Zoom Label:  {metadata.get('zoom_label', 'unknown')}")
    
    resolution = metadata.get("resolution", {})
    print(f"  Resolution:  {resolution.get('width', 'N/A')}x{resolution.get('height', 'N/A')}")
    print(f"  FPS:         {metadata.get('fps', 'N/A')}")
    print(f"  Created:     {cal.get('created_at', 'unknown')}")
    
    print("\nCalibration Points:")
    points = cal.get("calibration_points", [])
    print(f"  {'Y-Pixel':<12} {'Distance (ft)':<15}")
    print("  " + "-"*27)
    for y, dist in points:
        print(f"  {y:<12} {dist:<15}")
    
    print("\nTest Results Summary:")
    results = cal.get("test_results", [])
    if results:
        avg_error = sum(abs(r.get("error_percent", 0)) for r in results) / len(results)
        print(f"  Total tests: {len(results)}")
        print(f"  Avg error:   {avg_error:.2f}%")
    else:
        print("  No test results recorded.")
    
    print("\nDetection Coverage:")
    coverage = cal.get("detection_coverage")
    if coverage:
        print(f"  Total frames:     {coverage.get('total_frames', 'N/A')}")
        print(f"  Detected frames:  {coverage.get('detected_frames', 'N/A')}")
        print(f"  Coverage:         {coverage.get('percent_detected', 'N/A')}%")
        print(f"  Analyzed:         {coverage.get('timestamp', 'N/A')[:19]}")
    else:
        print("  No detection coverage analysis run.")
        print("  Use option [9] to analyze a video.")
    
    print("="*60)


def view_test_results():
    """View test results for a calibration."""
    cal_name = select_calibration("Select calibration to view results")
    if not cal_name:
        return
    
    results = get_test_results(cal_name)
    
    print("\n" + "="*60)
    print(f"TEST RESULTS: {cal_name}")
    print("="*60)
    
    if not results:
        print("No test results recorded.")
        print("="*60)
        return
    
    print(f"{'#':<4} {'Known':>10} {'Estimated':>12} {'Error':>10} {'Frame':>8} {'Timestamp':<20}")
    print("-"*70)
    
    total_error = 0
    for i, r in enumerate(results, 1):
        known = r.get("known_distance", 0)
        est = r.get("estimated_distance", 0)
        error = r.get("error_percent", 0)
        frame = r.get("frame_number", "N/A")
        timestamp = r.get("timestamp", "N/A")[:19]  # Trim to readable length
        
        print(f"{i:<4} {known:>10.1f} {est:>12.2f} {error:>9.1f}% {frame:>8} {timestamp:<20}")
        total_error += abs(error)
    
    avg_error = total_error / len(results)
    print("-"*70)
    print(f"Average absolute error: {avg_error:.2f}%")
    print(f"Total test points: {len(results)}")
    print("="*60)


def delete_calibration_interactive():
    """Interactively delete a calibration."""
    cal_name = select_calibration("Select calibration to DELETE")
    if not cal_name:
        return
    
    confirm = input(f"Are you sure you want to delete '{cal_name}'? (yes/no): ").strip().lower()
    if confirm == "yes":
        if delete_calibration(cal_name):
            print(f"Calibration '{cal_name}' deleted.")
        else:
            print("Failed to delete calibration.")
    else:
        print("Deletion cancelled.")


def test_video_interactive():
    """Interactively test a calibration with video."""
    cal_name = select_calibration("Select calibration to test")
    if not cal_name:
        return
    
    cal = get_calibration(cal_name)
    default_video = cal.get("metadata", {}).get("source_path") if cal else None
    
    print(f"\nDefault video: {default_video or 'None'}")
    video_input = input("Enter video path (or press Enter for default): ").strip()
    
    video_path = video_input if video_input else default_video
    
    if not video_path:
        print("No video path available. Please specify a video file.")
        video_path = input("Video path: ").strip()
        if not video_path:
            return
    
    run_video_test(cal_name, video_path)


def test_live_interactive():
    """Interactively test a calibration with live camera."""
    cal_name = select_calibration("Select calibration to test")
    if not cal_name:
        return
    
    points = get_calibration_points(cal_name)
    if not points or len(points) < 2:
        print("Calibration has insufficient points.")
        return
    
    load_model(points)
    test_model_live()


def analyze_detection_coverage_interactive():
    """Interactively analyze detection coverage for a video."""
    print("\n" + "-"*60)
    print("DETECTION COVERAGE ANALYSIS")
    print("-"*60)
    print("This will analyze what percentage of a video contains")
    print("detectable humans (independent of distance calibration).")
    print("-"*60)
    
    # Ask if user wants to associate with a calibration
    calibrations = list_calibrations()
    cal_name = None
    
    if calibrations:
        print("\nYou can optionally associate this analysis with a calibration")
        print("to store the results. Otherwise, results will only be printed.")
        print()
        associate = input("Associate with a calibration? (y/n): ").strip().lower()
        
        if associate == 'y':
            cal_name = select_calibration("Select calibration to store results")
    
    # Get video path
    default_video = None
    if cal_name:
        cal = get_calibration(cal_name)
        default_video = cal.get("metadata", {}).get("source_path") if cal else None
        if default_video:
            print(f"\nDefault video: {default_video}")
    
    video_input = input("Enter video path (or press Enter for default): ").strip()
    video_path = video_input if video_input else default_video
    
    if not video_path:
        print("No video path provided. Please specify a video file.")
        video_path = input("Video path: ").strip()
        if not video_path:
            print("Cancelled.")
            return
    
    # Ask about overlay
    show_overlay = input("\nShow live overlay during analysis? (y/n, default=y): ").strip().lower()
    show_overlay = show_overlay != 'n'
    
    # Run analysis
    results = run_detection_coverage_analysis(
        video_path=video_path,
        calibration_name=cal_name,
        show_overlay=show_overlay,
        save_results=(cal_name is not None)
    )
    
    if results:
        print("\nAnalysis completed successfully.")
    else:
        print("\nAnalysis was cancelled or failed.")


def main():
    """Main entry point."""
    print_header()
    
    while True:
        print_menu()
        
        try:
            choice = input("Enter choice: ").strip().lower()
            
            if choice == '1':
                list_all_calibrations()
            
            elif choice == '2':
                run_video_calibration()
            
            elif choice == '3':
                run_legacy_calibration()
            
            elif choice == '4':
                test_video_interactive()
            
            elif choice == '5':
                test_live_interactive()
            
            elif choice == '6':
                view_calibration_details()
            
            elif choice == '7':
                view_test_results()
            
            elif choice == '8':
                delete_calibration_interactive()
            
            elif choice == '9':
                analyze_detection_coverage_interactive()
            
            elif choice == 'q':
                print("\nExiting. Goodbye!")
                break
            
            else:
                print("Invalid choice. Please try again.")
        
        except KeyboardInterrupt:
            print("\n\nExiting. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            print("Please try again.")


if __name__ == "__main__":
    main()
