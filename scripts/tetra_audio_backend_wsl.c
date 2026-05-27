#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define FRAME_PREFIX 13
#define TRAFFIC_BYTES 1380
#define MIN_FRAME_BYTES (FRAME_PREFIX + TRAFFIC_BYTES)
#define PCM_CHUNK_BYTES 320

static volatile sig_atomic_t stopp_angefordert = 0;

static void signal_handler(int signum)
{
    (void)signum;
    stopp_angefordert = 1;
}

static void status_ausgeben(const char *text)
{
    fprintf(stderr, "[TETRA-Audio] %s\n", text);
    fflush(stderr);
}

static int schreibe_vollstaendig(int fd, const uint8_t *daten, size_t laenge)
{
    while (laenge > 0) {
        ssize_t geschrieben = write(fd, daten, laenge);
        if (geschrieben < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (geschrieben == 0) {
            return -1;
        }
        daten += geschrieben;
        laenge -= (size_t)geschrieben;
    }
    return 0;
}

static void fd_schliessen(int *fd)
{
    if (*fd >= 0) {
        close(*fd);
        *fd = -1;
    }
}

static void prozess_beenden(pid_t pid)
{
    if (pid <= 0) {
        return;
    }
    kill(pid, SIGTERM);
    for (int i = 0; i < 15; i++) {
        if (waitpid(pid, NULL, WNOHANG) == pid) {
            return;
        }
        struct timespec pause = {0, 100000000L};
        nanosleep(&pause, NULL);
    }
    kill(pid, SIGKILL);
    waitpid(pid, NULL, 0);
}

static pid_t starte_decoder(const char *programm, int stdin_fd, int stdout_fd)
{
    pid_t pid = fork();
    if (pid != 0) {
        return pid;
    }

    int devnull = open("/dev/null", O_WRONLY);
    dup2(stdin_fd, STDIN_FILENO);
    dup2(stdout_fd, STDOUT_FILENO);
    if (devnull >= 0) {
        dup2(devnull, STDERR_FILENO);
    }

    execl(programm, programm, "/dev/stdin", "/dev/stdout", (char *)NULL);
    _exit(127);
}

static int udp_socket_oeffnen(const char *host, int port)
{
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        return -1;
    }

    struct sockaddr_in adresse;
    memset(&adresse, 0, sizeof(adresse));
    adresse.sin_family = AF_INET;
    adresse.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, host, &adresse.sin_addr) != 1) {
        close(sock);
        return -1;
    }
    if (bind(sock, (struct sockaddr *)&adresse, sizeof(adresse)) < 0) {
        close(sock);
        return -1;
    }
    return sock;
}

static const char *argument_wert(int argc, char **argv, const char *name, const char *standard)
{
    for (int i = 1; i + 1 < argc; i++) {
        if (strcmp(argv[i], name) == 0) {
            return argv[i + 1];
        }
    }
    return standard;
}

int main(int argc, char **argv)
{
    const char *env_cdecoder = getenv("TETRA_CDECODER");
    const char *env_sdecoder = getenv("TETRA_SDECODER");
    const char *host = argument_wert(argc, argv, "--udp-host", "127.0.0.1");
    const char *port_text = argument_wert(argc, argv, "--udp-port", "");
    const char *cdecoder = argument_wert(
        argc, argv, "--cdecoder", env_cdecoder && *env_cdecoder ? env_cdecoder : "cdecoder");
    const char *sdecoder = argument_wert(
        argc, argv, "--sdecoder", env_sdecoder && *env_sdecoder ? env_sdecoder : "sdecoder");
    int port = atoi(port_text);
    int c_stdin[2] = {-1, -1};
    int c_to_s[2] = {-1, -1};
    int s_stdout[2] = {-1, -1};
    int udp_fd = -1;
    pid_t c_pid = -1;
    pid_t s_pid = -1;
    int rueckgabe = 0;

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    signal(SIGPIPE, SIG_IGN);

    if (port <= 0 || port > 65535) {
        status_ausgeben("ungültiger UDP-Port");
        return 2;
    }

    if (pipe(c_stdin) != 0 || pipe(c_to_s) != 0 || pipe(s_stdout) != 0) {
        status_ausgeben("Pipes konnten nicht geöffnet werden");
        return 2;
    }

    c_pid = starte_decoder(cdecoder, c_stdin[0], c_to_s[1]);
    s_pid = starte_decoder(sdecoder, c_to_s[0], s_stdout[1]);
    fd_schliessen(&c_stdin[0]);
    fd_schliessen(&c_to_s[0]);
    fd_schliessen(&c_to_s[1]);
    fd_schliessen(&s_stdout[1]);

    if (c_pid < 0 || s_pid < 0) {
        status_ausgeben("Codec-Prozesse konnten nicht gestartet werden");
        rueckgabe = 2;
        goto cleanup;
    }

    int flags = fcntl(s_stdout[0], F_GETFL, 0);
    if (flags >= 0) {
        fcntl(s_stdout[0], F_SETFL, flags | O_NONBLOCK);
    }

    udp_fd = udp_socket_oeffnen(host, port);
    if (udp_fd < 0) {
        status_ausgeben("UDP-Port konnte nicht geöffnet werden");
        rueckgabe = 2;
        goto cleanup;
    }

    fprintf(stderr, "[TETRA-Audio] hört auf UDP %s:%d\n", host, port);
    fflush(stderr);

    while (!stopp_angefordert) {
        struct pollfd fds[2];
        fds[0].fd = udp_fd;
        fds[0].events = POLLIN;
        fds[1].fd = s_stdout[0];
        fds[1].events = POLLIN | POLLHUP;

        int poll_result = poll(fds, 2, 250);
        if (poll_result < 0) {
            if (errno == EINTR) {
                continue;
            }
            rueckgabe = 2;
            break;
        }

        if (fds[0].revents & POLLIN) {
            uint8_t paket[2048];
            ssize_t gelesen = recvfrom(udp_fd, paket, sizeof(paket), 0, NULL, NULL);
            if (gelesen >= MIN_FRAME_BYTES && memcmp(paket, "TRA:", 4) == 0) {
                if (schreibe_vollstaendig(c_stdin[1], paket + FRAME_PREFIX, TRAFFIC_BYTES) != 0) {
                    status_ausgeben("Codec-Pipe wurde geschlossen");
                    rueckgabe = 4;
                    break;
                }
            }
        }

        if (fds[1].revents & (POLLIN | POLLHUP)) {
            uint8_t pcm[PCM_CHUNK_BYTES];
            for (;;) {
                ssize_t gelesen = read(s_stdout[0], pcm, sizeof(pcm));
                if (gelesen > 0) {
                    if (schreibe_vollstaendig(STDOUT_FILENO, pcm, (size_t)gelesen) != 0) {
                        stopp_angefordert = 1;
                        break;
                    }
                    continue;
                }
                if (gelesen == 0) {
                    status_ausgeben("Codec-Prozess wurde beendet");
                    rueckgabe = 3;
                    stopp_angefordert = 1;
                } else if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
                    rueckgabe = 3;
                    stopp_angefordert = 1;
                }
                break;
            }
        }

        if (waitpid(c_pid, NULL, WNOHANG) == c_pid || waitpid(s_pid, NULL, WNOHANG) == s_pid) {
            status_ausgeben("Codec-Prozess wurde beendet");
            rueckgabe = 3;
            break;
        }
    }

cleanup:
    fd_schliessen(&udp_fd);
    fd_schliessen(&c_stdin[1]);
    fd_schliessen(&s_stdout[0]);
    prozess_beenden(s_pid);
    prozess_beenden(c_pid);
    return rueckgabe;
}

/* © 2026 Erik Schauer, do1ffe@darc.de */
