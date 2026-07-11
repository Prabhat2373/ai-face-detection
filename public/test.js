const { Cam } = require("onvif");

new Cam(
  {
    hostname: "192.168.0.9",
    username: "admin",
    password: "Admin@1234",
    port: 80,
  },
  function (err) {
    if (err) {
      console.error(err);
      return;
    }

    console.log("Connected");

    this.getProfiles((err, profiles) => {
      if (err) return console.error(err);

      console.log(profiles);

      profiles.forEach((profile) => {
        this.getStreamUri(
          {
            protocol: "RTSP",
            profileToken: profile.$.token,
          },
          (err, uri) => {
            console.log(err || uri);
          },
        );
      });
    });
  },
);
