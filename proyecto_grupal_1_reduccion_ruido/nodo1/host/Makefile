# Compila el mismo sketch en la PC: sin ARDUINO definido, el .ino trae su propio main().
SKETCH = ../nodo1_esp32/nodo1_esp32.ino

nodo1_host: $(SKETCH)
	g++ -std=c++17 -O2 -Wall -Wextra -x c++ -o $@ $(SKETCH)

clean:
	rm -f nodo1_host
