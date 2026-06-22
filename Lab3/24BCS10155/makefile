CXX      = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -O2

clocksweep: clocksweep.cpp
	$(CXX) $(CXXFLAGS) -o clocksweep clocksweep.cpp

run: clocksweep
	./clocksweep

clean:
	rm -f clocksweep

.PHONY: run clean
