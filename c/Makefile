targets: syncjams

tinyosc/tinyosc.o: tinyosc/tinyosc.c tinyosc/tinyosc.h
	$(CC) -std=c99 -c tinyosc/tinyosc.c -Werror -O0 -g -o $@

syncjams.o: syncjams.c syncjams.h
	$(CC) -std=c99 -c syncjams.c -Werror -O0 -g -o $@

syncjams: main.c syncjams.o tinyosc/tinyosc.o
	$(CC) -std=c99 $^ -Werror -O0 -g -o $@

.PHONY: clean

clean:
	rm -f tinyosc/tinyosc.o syncjams.o syncjams
