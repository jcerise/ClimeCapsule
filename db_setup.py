from weather.clime_capsule import ClimeCapsule


def main():
    clime_capsule: ClimeCapsule = ClimeCapsule()
    clime_capsule.init_db()

if __name__ == '__main__':
    main()