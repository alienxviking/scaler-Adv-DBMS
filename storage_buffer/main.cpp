
template<typename T>
class ClockSweep
public:
   ClockSweep(int maxNumber): maxCacheSize(maxNumber) {};

   T getKey(T key){}

   void putKey(T key){}

private:
  uint maxCacheSize{0u};
  std::thread bgClockThread;
	
};
int main(){
	ClockSweep<int> clockSweep;

}
