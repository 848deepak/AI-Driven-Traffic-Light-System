#!/usr/bin/env python3
import time
import logging
from enum import Enum
from collections import deque

logger = logging.getLogger('traffic_logic')

class SignalState(Enum):
    """Enum for traffic light states"""
    RED = "RED"
    YELLOW = "YELLOW" 
    GREEN = "GREEN"

class TrafficController:
    """
    Traffic controller implementing timing logic for multiple lanes
    """
    def __init__(self, lane_ids, base_green_time=30, base_yellow_time=5):
        """
        Initialize traffic controller
        
        Args:
            lane_ids: List of lane IDs (e.g., ["L1", "L2"])
            base_green_time: Default green signal duration in seconds
            base_yellow_time: Default yellow signal duration in seconds
        """
        self.lane_ids = list(lane_ids)
        self.num_lanes = len(self.lane_ids)
        
        # Base signal timings
        self.base_green_time = base_green_time
        self.base_yellow_time = base_yellow_time
        self.base_red_time = base_green_time * (self.num_lanes - 1) + base_yellow_time * self.num_lanes
        
        # Signal timing modifiers
        self.min_green_time = 15  # Minimum green time
        self.max_green_time = 60  # Maximum green time for high traffic
        self.high_traffic_threshold = 5  # Number of vehicles considered "high traffic"
        
        # Empty lane threshold - will skip lanes with fewer vehicles than this
        self.empty_lane_threshold = 1  # Skip lanes with 0 vehicles
        
        # Current state
        self.current_lane_index = 0  # Index of current active (green) lane
        self.current_state = SignalState.GREEN
        self.current_state_start_time = time.time()
        self.current_state_duration = self.base_green_time
        
        # Signal override flags
        self.emergency_override = False
        self.emergency_lane = None
        
        # Initialize signal state for all lanes
        self.signal_states = {}
        self.initialize_signal_states()
        
        # Traffic density history (for potential advanced algorithms)
        self.traffic_history = {lane_id: deque(maxlen=10) for lane_id in self.lane_ids}
        
        # Last green time per lane to ensure fairness
        self.last_green_time = {lane_id: 0 for lane_id in self.lane_ids}
        self.max_green_time_without_service = 120  # Max time a lane can be red
        
        logger.info(f"Traffic controller initialized with {self.num_lanes} lanes")
    
    def initialize_signal_states(self):
        """Initialize the starting state of traffic signals"""
        # Set first lane to GREEN, all others to RED
        for i, lane_id in enumerate(self.lane_ids):
            if i == 0:
                self.signal_states[lane_id] = {
                    "state": SignalState.GREEN,
                    "time_left": self.base_green_time
                }
            else:
                self.signal_states[lane_id] = {
                    "state": SignalState.RED,
                    "time_left": self.base_green_time + (i-1) * (self.base_green_time + self.base_yellow_time)
                }
    
    def get_current_signal_states(self):
        """
        Get the current signal states for all lanes
        
        Returns:
            signal_states: Dictionary of lane signal states
        """
        return self.signal_states
    
    def update(self, lane_data):
        """
        Update signal states based on current traffic conditions
        
        Args:
            lane_data: Dictionary with lane data including traffic counts and emergency flags
            
        Returns:
            signal_states: Updated signal states for all lanes
        """
        current_time = time.time()
        elapsed_time = current_time - self.current_state_start_time
        active_lane_id = self.lane_ids[self.current_lane_index]
        
        # Check for emergency vehicle in any lane
        emergency_detected = False
        emergency_lane_id = None
        
        for lane_id, data in lane_data.items():
            # Store traffic count in history
            self.traffic_history[lane_id].append(data["count"])
            
            # Check for emergency vehicle
            if data["emergency"] and not self.emergency_override:
                emergency_detected = True
                emergency_lane_id = lane_id
                logger.info(f"Emergency vehicle detected in lane {lane_id}, preparing override")
        
        # Handle emergency vehicle override
        if emergency_detected and not self.emergency_override:
            self.handle_emergency(emergency_lane_id)
        
        # If we're in emergency override mode but no emergency vehicle is detected anymore
        elif self.emergency_override and not emergency_detected:
            # Keep the override for at least 10 more seconds to ensure the emergency vehicle passes
            if elapsed_time >= 10:
                self.emergency_override = False
                self.emergency_lane = None
                self.current_state_start_time = current_time
                logger.info("Emergency override ended, resuming normal operation")
        
        # Normal signal timing logic
        if not self.emergency_override:
            # Update remaining time for current state
            remaining_time = self.current_state_duration - elapsed_time
            
            # If current state time has elapsed, transition to next state
            if remaining_time <= 0:
                self.transition_state(lane_data)
                # Reset elapsed time
                self.current_state_start_time = current_time
                active_lane_id = self.lane_ids[self.current_lane_index]
            else:
                # Update time left for all lanes
                self.update_time_left(elapsed_time)
        
        # Create signal state representation for the hardware controller
        formatted_states = self.format_signal_states()
        return formatted_states
    
    def handle_emergency(self, emergency_lane_id):
        """
        Handle emergency vehicle detection
        
        Args:
            emergency_lane_id: Lane ID where emergency vehicle was detected
        """
        emergency_lane_index = self.lane_ids.index(emergency_lane_id)
        
        # If emergency is in a different lane than current green
        if emergency_lane_index != self.current_lane_index:
            # Set current lane to yellow first if it's green
            if self.current_state == SignalState.GREEN:
                self.current_state = SignalState.YELLOW
                self.current_state_duration = self.base_yellow_time
                self.current_state_start_time = time.time()
                self.signal_states[self.lane_ids[self.current_lane_index]]["state"] = SignalState.YELLOW
                self.signal_states[self.lane_ids[self.current_lane_index]]["time_left"] = self.base_yellow_time
                
                # Wait for yellow to complete
                time.sleep(self.base_yellow_time)
            
            # Set all signals to RED
            for lane_id in self.lane_ids:
                self.signal_states[lane_id]["state"] = SignalState.RED
                self.signal_states[lane_id]["time_left"] = 0
            
            # Set emergency lane to GREEN
            self.current_lane_index = emergency_lane_index
            self.signal_states[emergency_lane_id]["state"] = SignalState.GREEN
            self.signal_states[emergency_lane_id]["time_left"] = 30  # Give 30 seconds for emergency
        
        # Set emergency flags
        self.emergency_override = True
        self.emergency_lane = emergency_lane_id
        self.current_state = SignalState.GREEN
        self.current_state_start_time = time.time()
        self.current_state_duration = 30  # Extended green time for emergency
        
        logger.info(f"Emergency override active for lane {emergency_lane_id}")
    
    def transition_state(self, lane_data):
        """
        Transition to the next traffic signal state
        
        Args:
            lane_data: Current traffic data for all lanes
        """
        active_lane_id = self.lane_ids[self.current_lane_index]
        
        # State transition logic
        if self.current_state == SignalState.GREEN:
            # Update last green time for current lane
            self.last_green_time[active_lane_id] = time.time()
            
            # Green → Yellow transition
            self.current_state = SignalState.YELLOW
            self.current_state_duration = self.base_yellow_time
            self.signal_states[active_lane_id]["state"] = SignalState.YELLOW
            self.signal_states[active_lane_id]["time_left"] = self.base_yellow_time
            logger.info(f"Lane {active_lane_id} transitioning GREEN → YELLOW")
            
        elif self.current_state == SignalState.YELLOW:
            # Yellow → Red for current lane
            self.signal_states[active_lane_id]["state"] = SignalState.RED
            
            # Find next lane with traffic
            next_lane_index = self.select_next_lane(lane_data)
            self.current_lane_index = next_lane_index
            active_lane_id = self.lane_ids[self.current_lane_index]
            
            # Calculate green time based on traffic density
            green_time = self.calculate_green_time(active_lane_id, lane_data)
            
            # Set new lane to Green
            self.current_state = SignalState.GREEN
            self.current_state_duration = green_time
            self.signal_states[active_lane_id]["state"] = SignalState.GREEN
            self.signal_states[active_lane_id]["time_left"] = green_time
            
            # Update red time for other lanes
            self.update_red_times()
            
            logger.info(f"Lane {active_lane_id} transitioning to GREEN for {green_time}s")
            
    def select_next_lane(self, lane_data):
        """
        Select the next lane to turn green based on traffic
        
        Args:
            lane_data: Dictionary with lane data
            
        Returns:
            next_lane_index: Index of the next lane to service
        """
        current_time = time.time()
        current_index = self.current_lane_index
        candidate_lanes = []
        
        # First check if any lane has been waiting too long
        for i, lane_id in enumerate(self.lane_ids):
            if i == current_index:
                continue  # Skip current lane
            
            # Check if lane has been waiting too long
            wait_time = current_time - self.last_green_time.get(lane_id, 0)
            if wait_time > self.max_green_time_without_service:
                logger.info(f"Lane {lane_id} has waited too long ({wait_time:.1f}s), prioritizing")
                return i
        
        # Next, find lanes with traffic
        for i, lane_id in enumerate(self.lane_ids):
            if i == current_index:
                continue  # Skip current lane
            
            # Skip empty lanes unless all lanes are empty
            if lane_data[lane_id]["count"] >= self.empty_lane_threshold:
                candidate_lanes.append((i, lane_data[lane_id]["count"]))
        
        if candidate_lanes:
            # Sort by traffic count (descending)
            candidate_lanes.sort(key=lambda x: x[1], reverse=True)
            next_index = candidate_lanes[0][0]
            logger.info(f"Selected lane {self.lane_ids[next_index]} with {candidate_lanes[0][1]} vehicles")
            return next_index
        
        # If all lanes are empty (or below threshold), use round-robin approach
        next_index = (current_index + 1) % self.num_lanes
        logger.info(f"All lanes empty, using round-robin to select lane {self.lane_ids[next_index]}")
        return next_index
    
    def calculate_green_time(self, lane_id, lane_data):
        """
        Calculate green time based on traffic density
        
        Args:
            lane_id: Current lane ID
            lane_data: Current traffic data
            
        Returns:
            green_time: Calculated green signal duration
        """
        # Get current traffic count
        traffic_count = lane_data[lane_id]["count"]
        
        # No vehicles - minimum green time
        if traffic_count == 0:
            green_time = self.min_green_time
            logger.info(f"Lane {lane_id} has no vehicles, using minimum green time: {green_time}s")
        # High traffic - maximum green time
        elif traffic_count >= self.high_traffic_threshold:
            green_time = min(self.base_green_time + 15, self.max_green_time)
            logger.info(f"Lane {lane_id} has high traffic ({traffic_count} vehicles), extending green time: {green_time}s")
        # Low traffic - reduced green time
        elif traffic_count < self.empty_lane_threshold:
            green_time = max(self.base_green_time - 10, self.min_green_time)
            logger.info(f"Lane {lane_id} has low traffic ({traffic_count} vehicles), reducing green time: {green_time}s")
        # Normal traffic - standard green time
        else:
            green_time = self.base_green_time
            logger.info(f"Lane {lane_id} has normal traffic ({traffic_count} vehicles), standard green time: {green_time}s")
        
        return green_time
    
    def update_time_left(self, elapsed_time):
        """
        Update time left for all lanes
        
        Args:
            elapsed_time: Time elapsed since last state change
        """
        active_lane_id = self.lane_ids[self.current_lane_index]
        
        # Update active lane
        self.signal_states[active_lane_id]["time_left"] = max(0, self.current_state_duration - elapsed_time)
        
        # Update other lanes (they're all in RED state when not active)
        current_cycle_position = self.current_lane_index
        current_state = self.current_state
        
        # Calculate remaining time in current state
        remaining_in_current = self.signal_states[active_lane_id]["time_left"]
        
        # For each lane, calculate when it will turn GREEN
        for i, lane_id in enumerate(self.lane_ids):
            if i == current_cycle_position:
                continue  # Skip active lane
                
            # Calculate position relative to current
            position_diff = (i - current_cycle_position) % self.num_lanes
            
            # Time until this lane gets green
            time_to_green = remaining_in_current
            
            # If current lane is GREEN, add YELLOW time
            if current_state == SignalState.GREEN:
                time_to_green += self.base_yellow_time
            
            # Add time for lanes in between
            intervening_lanes = position_diff - 1 if position_diff > 0 else self.num_lanes - 1
            time_to_green += intervening_lanes * (self.base_green_time + self.base_yellow_time)
            
            self.signal_states[lane_id]["time_left"] = time_to_green
    
    def update_red_times(self):
        """Update red times for non-active lanes after a state transition"""
        active_lane_index = self.current_lane_index
        active_lane_id = self.lane_ids[active_lane_index]
        green_time = self.signal_states[active_lane_id]["time_left"]
        
        for i, lane_id in enumerate(self.lane_ids):
            if i == active_lane_index:
                continue  # Skip active lane
                
            # Calculate position relative to current active lane
            position_diff = (i - active_lane_index) % self.num_lanes
            
            # Time until this lane gets green
            time_to_green = green_time + self.base_yellow_time  # Current green + yellow time
            
            # Add time for lanes in between
            intervening_lanes = position_diff - 1 if position_diff > 0 else self.num_lanes - 1
            time_to_green += intervening_lanes * (self.base_green_time + self.base_yellow_time)
            
            self.signal_states[lane_id]["time_left"] = time_to_green
    
    def format_signal_states(self):
        """
        Format signal states for hardware controller
        
        Returns:
            formatted_states: String representation of signal states
        """
        state_strings = []
        
        for lane_id, state_info in self.signal_states.items():
            state_str = state_info["state"].value
            time_left = int(state_info["time_left"])
            state_strings.append(f"{lane_id}-{state_str}-{time_left}")
        
        return ";".join(state_strings)

if __name__ == "__main__":
    # Simple test code
    import random
    
    # Setup logging for testing
    logging.basicConfig(level=logging.INFO)
    
    # Create controller with 2 lanes
    lanes = ["L1", "L2"]
    controller = TrafficController(lanes)
    
    # Test for 30 seconds
    start_time = time.time()
    while time.time() - start_time < 30:
        # Generate random traffic data
        lane_data = {}
        emergency_lane = random.choice(lanes) if random.random() < 0.1 else None
        
        for lane in lanes:
            lane_data[lane] = {
                "count": random.randint(0, 10),
                "emergency": lane == emergency_lane
            }
        
        # Update controller
        signal_states = controller.update(lane_data)
        print(f"Signal states: {signal_states}")
        time.sleep(1) 